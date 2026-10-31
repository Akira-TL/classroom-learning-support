import io
import wave

import pytest
from test_auto_explanations import install_model
from test_evidence import Environment
from test_evidence import environment as environment
from test_tags import batch, periods


def wav_bytes(seconds: float = 3, value: int = 0) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(value.to_bytes(2, "little", signed=True) * int(seconds * 16000))
    return output.getvalue()


def create(environment: Environment):
    return environment.client.post(f"/api/classrooms/{environment.cid}/care/tag-batches", json=batch()).json()


def test_wav_binding_needs_no_asr_events_and_becomes_readable_in_history(environment: Environment):
    record = create(environment)
    assert not any(item.session_id == record["session_id"] for item in environment.speech.events(environment.cid))
    url = f"/api/classrooms/{environment.cid}/care/tag-batches/{record['id']}/audio"
    assert environment.client.get(url).status_code == 404
    content = wav_bytes()
    uploaded = environment.client.post(url, content=content, headers={"Content-Type": "audio/wav"})
    assert uploaded.status_code == 200 and uploaded.json()["duration_ms"] == 3000
    fetched = environment.client.get(url)
    assert fetched.status_code == 200 and fetched.content == content
    assert fetched.headers["cache-control"] == "no-store"
    history = environment.client.get(
        f"/api/classrooms/{environment.cid}/care/students/student-01/history").json()
    assert history["tag_batches"][0]["audio_asset"]["id"] == uploaded.json()["id"]
    assert history["tag_batches"][0]["audio_asset"]["source"] == "provided_tag_batch_audio"


def test_raw_audio_cannot_be_overwritten(environment: Environment):
    record = create(environment)
    url = f"/api/classrooms/{environment.cid}/care/tag-batches/{record['id']}/audio"
    first = wav_bytes()
    assert environment.client.post(url, content=first, headers={"Content-Type": "audio/wav"}).status_code == 200
    changed = environment.client.post(url, content=wav_bytes(value=10), headers={"Content-Type": "audio/wav"})
    assert changed.status_code == 409
    assert environment.client.get(url).content == first


@pytest.mark.parametrize("username", ["student-01", "parent-01", "teacher-02", "admin-01"])
def test_only_classroom_teacher_can_upload_or_read_mixed_audio(environment: Environment, username: str):
    record = create(environment)
    url = f"/api/classrooms/{environment.cid}/care/tag-batches/{record['id']}/audio"
    assert environment.client.post(url, content=wav_bytes(), headers={"Content-Type": "audio/wav"}).status_code == 200
    environment.client.post("/api/auth/login", json={"username": username, "password": "evidence-test-password"})
    assert environment.client.get(url).status_code == 403
    assert environment.client.post(url, content=wav_bytes(), headers={"Content-Type": "audio/wav"}).status_code == 403


def test_bad_format_or_time_range_does_not_attach_an_audio_asset(environment: Environment):
    record = create(environment)
    url = f"/api/classrooms/{environment.cid}/care/tag-batches/{record['id']}/audio"
    assert environment.client.post(url, content=b"mp3", headers={"Content-Type": "audio/mpeg"}).status_code == 415
    assert environment.client.post(url, content=b"bad", headers={"Content-Type": "audio/wav"}).status_code == 422
    short = environment.client.post(url, content=wav_bytes(0.5), headers={"Content-Type": "audio/wav"})
    assert short.status_code == 422
    history = environment.client.get(
        f"/api/classrooms/{environment.cid}/care/students/student-01/history").json()
    assert history["tag_batches"][0]["audio_asset"] is None


def test_audio_attachment_invalidates_explanation_fingerprint(environment: Environment, monkeypatch):
    record = create(environment)
    calls = []
    install_model(monkeypatch, calls)
    request = {"comparison": periods(), "perspective": "teacher"}
    endpoint = f"/api/classrooms/{environment.cid}/care/explanations"
    before = environment.client.post(endpoint, json=request).json()
    upload = environment.client.post(
        f"/api/classrooms/{environment.cid}/care/tag-batches/{record['id']}/audio",
        content=wav_bytes(), headers={"Content-Type": "audio/wav"})
    assert upload.status_code == 200
    after = environment.client.post(endpoint, json=request).json()
    assert before["source_fingerprint"] != after["source_fingerprint"]
    assert len(calls) == 2
