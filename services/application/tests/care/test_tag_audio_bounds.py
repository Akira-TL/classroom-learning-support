import pytest
from test_evidence import Environment
from test_evidence import environment as environment
from test_tag_audio import create, wav_bytes
from test_tags import batch


@pytest.mark.parametrize("kind", ["tag", "transcript"])
def test_revision_cannot_move_timestamps_outside_archived_audio(environment: Environment, kind: str):
    record = create(environment)
    base = f"/api/classrooms/{environment.cid}/care/tag-batches"
    audio_url = f"{base}/{record['id']}/audio"
    archived = environment.client.post(audio_url, content=wav_bytes(3), headers={"Content-Type": "audio/wav"})
    assert archived.status_code == 200
    payload = batch() | {"expected_revision": 1}
    if kind == "tag":
        payload["tags"][0]["end_ms"] = 4000
    else:
        payload["transcripts"] = [{"start_ms": 2000, "end_ms": 4000, "text": "越出已归档音频的转写"}]
    rejected = environment.client.put(f"{base}/{record['id']}", json=payload)
    assert rejected.status_code == 422
    latest = environment.client.get(base).json()[0]
    assert latest["revision"] == 1 and latest["tags"][0]["end_ms"] == 2000 and latest["transcripts"] == []
    assert latest["audio_asset"]["id"] == archived.json()["id"]
    assert environment.client.get(audio_url).content == wav_bytes(3)
    narrower = batch() | {"expected_revision": 1, "source_description": "已缩小时间范围并补充来源说明"}
    narrower["tags"][0]["end_ms"] = 1500
    accepted = environment.client.put(f"{base}/{record['id']}", json=narrower)
    assert accepted.status_code == 200 and accepted.json()["revision"] == 2


def test_switching_session_validates_against_destination_audio_before_rebinding(environment: Environment):
    record = create(environment)
    base = f"/api/classrooms/{environment.cid}/care/tag-batches"
    target = batch() | {"import_id": "target-session-import", "session_id": "target-session",
                        "student_id": "student-02", "source_name": "target.wav"}
    holder = environment.client.post(base, json=target).json()
    audio = wav_bytes(3)
    archived = environment.client.post(f"{base}/{holder['id']}/audio", content=audio,
                                        headers={"Content-Type": "audio/wav"})
    assert archived.status_code == 200
    changed = batch() | {"expected_revision": 1, "session_id": "target-session", "source_version": "v2"}
    changed["tags"][0]["end_ms"] = 4000
    assert environment.client.put(f"{base}/{record['id']}", json=changed).status_code == 422
    original = next(item for item in environment.client.get(base).json() if item["id"] == record["id"])
    assert original["session_id"] == record["session_id"] and original["revision"] == 1
    assert original["audio_asset"] is None
    assert environment.client.get(f"{base}/{holder['id']}/audio").content == audio
    changed["tags"][0]["end_ms"] = 3000
    valid = environment.client.put(f"{base}/{record['id']}", json=changed)
    assert valid.status_code == 200 and valid.json()["revision"] == 2
    assert valid.json()["audio_asset"]["id"] == archived.json()["id"]
    assert environment.client.get(f"{base}/{record['id']}/audio").content == audio


def test_new_unarchived_session_remains_available_for_replacement_source(environment: Environment):
    record = create(environment)
    base = f"/api/classrooms/{environment.cid}/care/tag-batches"
    archived = environment.client.post(f"{base}/{record['id']}/audio", content=wav_bytes(3),
                                        headers={"Content-Type": "audio/wav"})
    assert archived.status_code == 200
    changed = batch() | {"expected_revision": 1, "session_id": "new-unarchived-session", "source_version": "v2"}
    changed["tags"][0]["end_ms"] = 5000
    accepted = environment.client.put(f"{base}/{record['id']}", json=changed)
    assert accepted.status_code == 200 and accepted.json()["revision"] == 2
    assert accepted.json()["audio_asset"] is None
    assert environment.client.get(f"{base}/{record['id']}/audio").status_code == 404
