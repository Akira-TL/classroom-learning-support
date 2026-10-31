from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_evidence import Environment
from test_evidence import environment as environment
from test_tag_audio import create, wav_bytes
from test_tags import batch

from teaching.audio.media import AudioStore


def test_revision_committed_before_archive_cannot_attach_audio_checked_against_old_tags(
    environment: Environment, monkeypatch,
):
    record = create(environment)
    original_save = AudioStore.save

    def writer_wins_archive_boundary(store, cid, sid, content, **options):
        # 仅控制调度：另一条真实PUT请求在归档进入写事务前完成。
        revised = batch() | {"expected_revision": 1, "source_version": "v2"}
        revised["tags"][0]["end_ms"] = 5000
        with TestClient(environment.client.app) as writer:
            writer.cookies.update(environment.client.cookies)
            changed = writer.put(f"/api/classrooms/{cid}/care/tag-batches/{record['id']}", json=revised)
            assert changed.status_code == 200
        return original_save(store, cid, sid, content, **options)

    monkeypatch.setattr(AudioStore, "save", writer_wins_archive_boundary)
    url = f"/api/classrooms/{environment.cid}/care/tag-batches/{record['id']}/audio"
    response = environment.client.post(url, content=wav_bytes(3), headers={"Content-Type": "audio/wav"})
    assert response.status_code == 409
    assert environment.client.get(url).status_code == 404
    records = environment.client.get(f"/api/classrooms/{environment.cid}/care/tag-batches").json()
    assert records[0]["revision"] == 2 and records[0]["audio_asset"] is None


def test_file_write_failure_rolls_back_binding_and_removes_partial_archive(environment: Environment, monkeypatch):
    record = create(environment)
    original_write = Path.write_bytes
    audio_directory = environment.store.path.parent / "audio"
    before = set(audio_directory.glob("*.wav"))

    def interrupted_write(path: Path, content: bytes) -> int:
        if path.parent == audio_directory and path.suffix == ".wav":
            original_write(path, content[:20])
            raise OSError("synthetic interrupted audio write")
        return original_write(path, content)

    url = f"/api/classrooms/{environment.cid}/care/tag-batches/{record['id']}/audio"
    with monkeypatch.context() as failure:
        failure.setattr(Path, "write_bytes", interrupted_write)
        with pytest.raises(OSError, match="synthetic interrupted"):
            environment.client.post(url, content=wav_bytes(3), headers={"Content-Type": "audio/wav"})
    assert set(audio_directory.glob("*.wav")) == before
    assert environment.client.get(url).status_code == 404
    retry = environment.client.post(url, content=wav_bytes(3), headers={"Content-Type": "audio/wav"})
    assert retry.status_code == 200
    assert environment.client.get(url).content == wav_bytes(3)
