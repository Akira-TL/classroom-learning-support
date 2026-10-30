import base64
import io
import sqlite3
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier, Lock

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from test_speech_api import classroom_api as classroom_api
from test_speech_api import login

from teaching.audio.media import AudioAsset, AudioStore
from teaching.classroom.storage import StoreError
from teaching.deletion.models import DeleteClassroom
from teaching.deletion.store import DeletionStore
from teaching.inputs.archive import pcm_wav
from teaching.inputs.models import InputFrame, InputSession
from teaching.inputs.store import InputStore


@dataclass
class Environment:
    client: TestClient
    cid: str

    @property
    def url(self) -> str:
        return f"/api/classrooms/{self.cid}/input-sessions"

    def create(self, mode: str = "file_stream") -> InputSession:
        response = self.client.post(
            self.url,
            json={
                "input_mode": mode,
                "sample_rate": 16000,
                "channels": 1,
                "encoding": "pcm_s16le",
            },
        )
        assert response.status_code == 200
        return InputSession.model_validate_json(response.content)

    def frame(self, sid: str, raw: bytes, sequence: int = 0, start: int = 0):
        return self.client.post(
            f"{self.url}/{sid}/frames",
            content=InputFrame(
                sequence=sequence,
                start_sample=start,
                frame_count=len(raw) // 2,
                pcm_base64=base64.b64encode(raw).decode(),
            ).model_dump_json(),
        )


@pytest.fixture
def env(classroom_api: tuple[TestClient, str]) -> Environment:
    client, speech_url = classroom_api
    return Environment(client, speech_url.split("/")[-2])


@pytest.mark.parametrize("mode", ["file_stream", "microphone"])
def test_pcm_reassembles_exact_wav_without_recognition(env: Environment, mode: str) -> None:
    session = env.create(mode)
    first = b"\0\0\xff\x7f\0\x80\x01\0" * 200
    second = b"\x02\0\xfe\xff" * 400
    assert env.frame(session.id, first).status_code == 200
    duplicate = InputSession.model_validate_json(env.frame(session.id, first).content)
    assert duplicate.received_samples == 800
    assert env.frame(session.id, second, sequence=1, start=800).status_code == 200
    response = env.client.post(f"{env.url}/{session.id}/finish", json={})
    result = InputSession.model_validate_json(response.content)
    assert result.status == "ended"
    assert result.processing_mode == "capture_only" and result.recognizer_connected is False
    assert result.audio_asset.source == f"{mode}_capture_only"
    assert result.audio_asset.duration_ms == 100
    playback = env.client.get(f"{env.url}/{session.id}/audio")
    with wave.open(io.BytesIO(playback.content), "rb") as audio:
        assert audio.getframerate() == 16000 and audio.getnchannels() == 1
        assert audio.getsampwidth() == 2 and audio.getnframes() == 1600
        assert audio.readframes(1600) == first + second
    repeated = InputSession.model_validate_json(env.client.post(f"{env.url}/{session.id}/finish", json={}).content)
    assert repeated.audio_asset.id == result.audio_asset.id
    speech = env.client.get(f"/api/classrooms/{env.cid}/speech/timeline")
    assert speech.json() == []


def test_missing_conflicting_invalid_frames_and_pause_state(env: Environment) -> None:
    session = env.create()
    raw = b"\0\0" * 160
    assert env.frame(session.id, raw, sequence=1).status_code == 409
    assert env.frame(session.id, raw, start=10).status_code == 409
    assert env.frame(session.id, raw).status_code == 200
    assert env.frame(session.id, b"\x01\0" * 160).status_code == 409
    for encoded, count in (("not base64", 1), ("AA==", 1), (" AAAA ", 1)):
        assert (
            env.client.post(
                f"{env.url}/{session.id}/frames",
                json={
                    "sequence": 1,
                    "start_sample": 160,
                    "frame_count": count,
                    "pcm_base64": encoded,
                },
            ).status_code
            == 422
        )
    assert env.client.put(f"{env.url}/{session.id}/state", json={"action": "pause"}).status_code == 200
    assert env.frame(session.id, raw, sequence=1, start=160).status_code == 409
    assert env.client.put(f"{env.url}/{session.id}/state", json={"action": "resume"}).status_code == 200
    assert env.frame(session.id, raw, sequence=1, start=160).status_code == 200
    mic = env.create("microphone")
    assert env.client.put(f"{env.url}/{mic.id}/state", json={"action": "pause"}).status_code == 409


def test_interrupted_input_and_limits_do_not_pretend_success(env: Environment, monkeypatch: pytest.MonkeyPatch) -> None:
    session = env.create("microphone")
    assert env.frame(session.id, b"\0\0" * 100).status_code == 200
    result = InputSession.model_validate_json(
        env.client.post(
            f"{env.url}/{session.id}/finish",
            json={"interrupted": True},
        ).content
    )
    assert result.status == "failed" and result.audio_asset is None
    assert result.received_samples == 100
    assert env.client.get(f"{env.url}/{session.id}/audio").status_code == 404
    assert env.frame(session.id, b"\0\0", sequence=1, start=100).status_code == 409
    limited = env.create()
    monkeypatch.setattr(AudioStore, "max_bytes", 64)
    assert env.frame(limited.id, b"\0\0" * 32).status_code == 413
    state = InputSession.model_validate_json(env.client.get(f"{env.url}/{limited.id}").content)
    assert state.received_samples == state.expected_sequence == 0


def test_permissions_and_deleted_sessions_reject_late_frames(env: Environment) -> None:
    session = env.create()
    env.frame(session.id, b"\0\0" * 100)
    for username in ("teacher-02", "student-01", "parent-01", "admin-01"):
        login(env.client, username)
        assert env.client.get(env.url).status_code == 403
        assert env.client.get(f"{env.url}/{session.id}/audio").status_code == 403
        assert env.frame(session.id, b"\0\0").status_code == 403
    login(env.client)
    store = env.client.app.state.store
    classroom = store.get_classroom("teacher-01", env.cid)
    DeletionStore(store).create(
        env.cid,
        "teacher-01",
        DeleteClassroom(
            expected_revision=1,
            confirmation=classroom.title,
            idempotency_key="delete-input-01",
        ),
    )
    assert env.frame(session.id, b"\0\0", sequence=1, start=100).status_code == 410
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM input_frames WHERE classroom_id=?", (env.cid,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM input_sessions WHERE classroom_id=?", (env.cid,)).fetchone()[0] == 0


def test_finish_duplicate_during_archive_does_not_override(env: Environment, monkeypatch: pytest.MonkeyPatch) -> None:
    session = env.create()
    env.frame(session.id, b"\0\0" * 100)
    original = AudioStore.save

    def save(
        self: AudioStore, cid: str, sid: str, content: bytes, *, source: str = "teacher_uploaded_audio"
    ) -> AudioAsset:
        duplicate = InputSession.model_validate_json(env.client.post(f"{env.url}/{sid}/finish", json={}).content)
        assert duplicate.status == "finishing" and duplicate.audio_asset is None
        return original(self, cid, sid, content, source=source)

    monkeypatch.setattr(AudioStore, "save", save)
    result = InputSession.model_validate_json(env.client.post(f"{env.url}/{session.id}/finish", json={}).content)
    assert result.status == "ended"
    assert len(TypeAdapter(list[InputSession]).validate_json(env.client.get(env.url).content)) == 1


def test_delete_during_archive_cannot_restore_audio(env: Environment, monkeypatch: pytest.MonkeyPatch) -> None:
    session = env.create()
    env.frame(session.id, b"\0\0" * 100)
    original = AudioStore.save
    store = env.client.app.state.store
    classroom = store.get_classroom("teacher-01", env.cid)

    def save(
        self: AudioStore, cid: str, sid: str, content: bytes, *, source: str = "teacher_uploaded_audio"
    ) -> AudioAsset:
        DeletionStore(store).create(
            cid,
            "teacher-01",
            DeleteClassroom(
                expected_revision=1,
                confirmation=classroom.title,
                idempotency_key="delete-in-finish-01",
            ),
        )
        return original(self, cid, sid, content, source=source)

    monkeypatch.setattr(AudioStore, "save", save)
    assert env.client.post(f"{env.url}/{session.id}/finish", json={}).status_code == 410
    assert list((store.path.parent / "audio").iterdir()) == []


def finishing(env: Environment, monkeypatch: pytest.MonkeyPatch, archived: bool = False) -> InputSession:
    session = env.create()
    env.frame(session.id, b"\x01\0" * 160)
    original = InputStore._save

    def crash_after_archive(self: InputStore, db: sqlite3.Connection, current: InputSession) -> None:
        if current.status == "ended":
            raise RuntimeError("simulated crash after archive")
        original(self, db, current)

    def crash_before_archive(audio: AudioStore, current: InputSession, frames: list[bytes]) -> AudioAsset:
        raise RuntimeError("simulated crash before archive")

    with monkeypatch.context() as patch:
        if archived:
            patch.setattr(InputStore, "_save", crash_after_archive)
        else:
            patch.setattr("teaching.inputs.store.archive_or_recover", crash_before_archive)
        with pytest.raises(RuntimeError, match="simulated crash"):
            env.client.post(f"{env.url}/{session.id}/finish", json={})
    state = InputSession.model_validate_json(env.client.get(f"{env.url}/{session.id}").content)
    assert state.status == "finishing"
    return state


@pytest.mark.parametrize("archived", [False, True])
def test_explicit_recovery_handles_both_crash_points(
    env: Environment,
    monkeypatch: pytest.MonkeyPatch,
    archived: bool,
) -> None:
    session = finishing(env, monkeypatch, archived)
    repeated = InputSession.model_validate_json(env.client.post(f"{env.url}/{session.id}/finish", json={}).content)
    assert repeated.status == "finishing"
    response = env.client.post(f"{env.url}/{session.id}/recover")
    recovered = InputSession.model_validate_json(response.content)
    assert recovered.status == "ended" and recovered.audio_asset is not None
    assert recovered.recognizer_connected is False
    assert env.client.post(f"{env.url}/{session.id}/recover").status_code == 409


@pytest.mark.parametrize("mismatch", ["source", "pcm", "rate"])
def test_recovery_never_adopts_mismatched_existing_audio(
    env: Environment,
    monkeypatch: pytest.MonkeyPatch,
    mismatch: str,
) -> None:
    session = finishing(env, monkeypatch)
    audio = AudioStore(env.client.app.state.store.path)
    pcm = b"\0\0" * 160 if mismatch == "pcm" else b"\x01\0" * 160
    rendered_session = session.model_copy(update={"sample_rate": 8000}) if mismatch == "rate" else session
    existing = audio.save(
        env.cid,
        session.id,
        pcm_wav(rendered_session, [pcm]),
        source="teacher_uploaded_audio" if mismatch == "source" else "file_stream_capture_only",
    )
    before = audio.get(env.cid, session.id)[1].read_bytes()
    assert env.client.post(f"{env.url}/{session.id}/recover").status_code == 409
    assert audio.get(env.cid, session.id)[0].id == existing.id
    assert audio.get(env.cid, session.id)[1].read_bytes() == before
    assert InputSession.model_validate_json(env.client.get(f"{env.url}/{session.id}").content).status == "finishing"


def test_two_explicit_recoveries_archive_only_one_copy(env: Environment, monkeypatch: pytest.MonkeyPatch) -> None:
    session = finishing(env, monkeypatch)
    barrier = Barrier(2)
    guard = Lock()
    count = [0]
    original = AudioStore.get

    def get(self: AudioStore, cid: str, sid: str):
        try:
            return original(self, cid, sid)
        except StoreError as error:
            with guard:
                count[0] += 1
                waiting = count[0] <= 2
            if error.status == 404 and waiting:
                barrier.wait(timeout=10)
            raise

    monkeypatch.setattr(AudioStore, "get", get)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(env.client.post, f"{env.url}/{session.id}/recover") for _ in range(2)]
        results = [InputSession.model_validate_json(future.result(timeout=20).content) for future in futures]
    assert results[0].audio_asset.id == results[1].audio_asset.id
    with env.client.app.state.store.connection() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM audio_assets WHERE classroom_id=? AND session_id=?", (env.cid, session.id)
            ).fetchone()[0]
            == 1
        )


def test_recovery_is_owner_only_and_rejects_after_deletion(env: Environment, monkeypatch: pytest.MonkeyPatch) -> None:
    session = finishing(env, monkeypatch)
    login(env.client, "teacher-02")
    assert env.client.post(f"{env.url}/{session.id}/recover").status_code == 403
    login(env.client)
    store = env.client.app.state.store
    classroom = store.get_classroom("teacher-01", env.cid)
    DeletionStore(store).create(
        env.cid,
        "teacher-01",
        DeleteClassroom(
            expected_revision=1,
            confirmation=classroom.title,
            idempotency_key="delete-recovery-01",
        ),
    )
    assert env.client.post(f"{env.url}/{session.id}/recover").status_code == 410
