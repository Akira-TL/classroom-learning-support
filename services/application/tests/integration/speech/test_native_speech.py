"""原生生产者事件跨过可信入口后的数据保真与权限门禁。"""

import httpx
import pytest
from test_evidence import Environment
from test_evidence import environment as environment

from teaching.audio.models import ReviewRequest
from teaching.audio.store import SpeechConflict
from teaching.integration.native_models import AudioRef, NativeIngest, NativeSpeechEvent, SourceRecord

TOKEN = "native-speech-test-token-at-least-32-characters"


def event(kind: str = "transcript.final", sequence: int = 2) -> NativeSpeechEvent:
    return NativeSpeechEvent.model_validate({
        "session_id": "ses_native", "event_id": f"evt_{sequence}", "sequence": sequence,
        "event_type": kind, "segment_id": "seg_1", "start_ms": 1000, "end_ms": 2000,
        "revision": 1, "text": "需要平均分" if kind.startswith("transcript.") else None,
        "data_origin": "file_replay", "reliability_state": "needs_review",
    })


def send(env: Environment, native: NativeSpeechEvent, token: str = TOKEN) -> httpx.Response:
    return env.client.post("/api/integrations/speech/native-events", headers={"Authorization": f"Bearer {token}"},
                           content=NativeIngest(classroom_id=env.cid, event=native).model_dump_json(by_alias=True))


@pytest.fixture
def connected(environment: Environment, monkeypatch: pytest.MonkeyPatch) -> Environment:
    monkeypatch.setenv("SPEECH_INGEST_TOKEN", TOKEN)
    return environment


def test_complete_payload_survives_and_duplicate_does_not_reopen_review(connected: Environment) -> None:
    source = SourceRecord(source_id="spk01", kind="azimuth", value=25.5, unit="deg", reference="mic_pair_broadside",
                          valid_from_ms=1000, valid_to_ms=2000, reliability_state="needs_review", rebind_hint=True)
    position = event("source.position", 1).model_copy(update={"sources": [source]})
    assert send(connected, position).status_code == 200
    native = event().model_copy(update={
        "audio_ref": [AudioRef(id="aud_raw"), AudioRef(id="aud_sep", kind="separated", offset_ms=1000)],
        "diagnostics": {"engine": "funasr", "review_reasons": ["math_term"], "score": 0.4},
    })
    assert send(connected, native).status_code == 200
    stored = next(u for u in connected.speech.timeline(connected.cid) if u.session_id == "ses_native")
    assert stored.native_event and stored.native_event.sources == [source]
    assert stored.native_event.audio_ref[1].offset_ms == 1000
    assert stored.native_event.diagnostics == native.diagnostics
    assert stored.student_alias is None and stored.identity_review == "pending"
    connected.speech.review(connected.cid, stored.session_id, stored.segment_id, "teacher-01", ReviewRequest(
        expected_version=1, text_review="confirmed", identity_review="pending", question_review="pending"))
    assert send(connected, native).json() == {"created": False}
    latest = next(u for u in connected.speech.timeline(connected.cid) if u.session_id == "ses_native")
    assert latest.version == 2 and latest.text_review == "confirmed"
    conflict = native.model_copy(update={"text": "冲突内容"})
    assert send(connected, conflict).status_code == 409
    archived = connected.speech.events(connected.cid)
    assert next(e.native_event for e in archived if e.event_id == native.event_id) == native


def test_failed_recognition_is_preserved_and_empty_text_cannot_be_confirmed(connected: Environment) -> None:
    failed = event().model_copy(update={"text": None, "reliability_state": "failed", "status": "asr_unavailable"})
    assert send(connected, failed).status_code == 200
    stored = next(u for u in connected.speech.timeline(connected.cid) if u.session_id == "ses_native")
    assert stored.upstream_text == "" and stored.native_event.status == "asr_unavailable"
    with pytest.raises(SpeechConflict, match="补充教师"):
        connected.speech.review(connected.cid, stored.session_id, stored.segment_id, "teacher-01", ReviewRequest(
            expected_version=1, text_review="confirmed", identity_review="pending", question_review="pending"))


def test_origin_auth_and_ended_session_gates(connected: Environment) -> None:
    assert send(connected, event(), "wrong").status_code == 401
    assert send(connected, event().model_copy(update={"data_origin": "simulated"})).status_code == 409
    oracle = event().model_copy(update={"diagnostics": {"engine": "oracle_script_by_time"}})
    assert send(connected, oracle).status_code == 409
    assert send(connected, event()).status_code == 200
    ended = event("session.ended", 3).model_copy(update={"segment_id": None, "status": "completed"})
    assert send(connected, ended).status_code == 200
    assert send(connected, event("transcript.revised", 4).model_copy(update={"revision": 2})).status_code == 409


def test_late_position_invalidates_review_and_older_transcript_cannot_override(connected: Environment) -> None:
    assert send(connected, event()).status_code == 200
    review = ReviewRequest(expected_version=1, text_review="confirmed", identity_review="confirmed",
                           question_review="confirmed", student_alias="student-01", question_id="q-1")
    connected.speech.review(connected.cid, "ses_native", "seg_1", "teacher-01", review)
    source = SourceRecord(source_id="src_spk", kind="anon_speaker", value="spk_02", unit="label",
                          reference="session", valid_from_ms=1000, valid_to_ms=2000,
                          reliability_state="needs_review", rebind_hint=True)
    assert send(connected, event("source.position", 3).model_copy(update={"sources": [source]})).status_code == 200
    stored = next(u for u in connected.speech.timeline(connected.cid) if u.session_id == "ses_native")
    assert stored.version == 3 and stored.identity_review == "pending"
    assert stored.native_event.sources[0].rebind_hint
    revised = event("transcript.revised", 4).model_copy(update={"revision": 2, "text": "修订结果"})
    assert send(connected, revised).status_code == 200
    older = event("transcript.final", 5).model_copy(update={"text": "旧结果"})
    assert send(connected, older).status_code == 200
    latest = next(u for u in connected.speech.timeline(connected.cid) if u.session_id == "ses_native")
    assert latest.upstream_text == "修订结果" and latest.revision == 2 and latest.version == 4


def test_replacements_withdraw_previous_segment(connected: Environment) -> None:
    assert send(connected, event()).status_code == 200
    newer = NativeSpeechEvent.model_validate(event().model_dump() | {
        "event_id": "evt_new", "sequence": 3, "segment_id": "seg_2",
        "replaces": {"segments": ["seg_1"], "revisions": [1]},
        "overlap": {"present": True, "with": ["seg_3"]},
    })
    assert send(connected, newer).status_code == 200
    rows = {u.segment_id: u for u in connected.speech.timeline(connected.cid) if u.session_id == "ses_native"}
    assert rows["seg_1"].phase == "withdraw" and rows["seg_1"].version == 2
    assert rows["seg_2"].native_event.overlap.with_segments == ["seg_3"]


def test_track_requires_classroom_teacher_and_declared_reference(
    connected: Environment, monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = event().model_copy(update={"audio_ref": [AudioRef(id="aud_raw")]})
    assert send(connected, native).status_code == 200
    calls: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=b"RIFF\x04\x00\x00\x00WAVEdata")

    original = httpx.Client
    monkeypatch.setattr("teaching.integration.tracks.httpx.Client",
                        lambda **kw: original(transport=httpx.MockTransport(upstream), **kw))
    url = f"/api/classrooms/{connected.cid}/speech/ses_native/seg_1/tracks/aud_raw"
    assert connected.client.get(url).status_code == 200
    assert str(calls[0].url) == "http://127.0.0.1:8765/v1/audio/ses_native/ref/aud_raw"
    assert connected.client.get(url.replace("aud_raw", "unknown")).status_code == 404
    assert len(calls) == 1
    for username in ("parent-01", "student-01", "teacher-02"):
        connected.client.post("/api/auth/login", json={"username": username, "password": "evidence-test-password"})
        assert connected.client.get(url).status_code in {403, 404}
    assert len(calls) == 1
