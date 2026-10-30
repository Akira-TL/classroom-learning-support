import io
import wave
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, TypeAdapter

from teaching.api import create_app
from teaching.audio.api import EventReceipt
from teaching.audio.models import ReviewRequest, SpeechEvent, Utterance
from teaching.classroom.auth import AuthSettings
from teaching.classroom.classrooms import Classroom, CreateClassroom, Question


def test_audio_archive_playback_range_and_permissions(
    classroom_api: tuple[TestClient, str],
    event: SpeechEvent,
) -> None:
    client, url = classroom_api
    assert client.post(f"{url}/events", content=event.model_dump_json()).status_code == 200
    data = io.BytesIO()
    with wave.open(data, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 32000)
    content = data.getvalue()
    upload = client.post(f"{url}/session-01/audio", content=content, headers={"Content-Type": "audio/wav"})
    assert upload.status_code == 200
    assert upload.json()["duration_ms"] == 2000
    assert client.get(f"{url}/timeline").json()[0]["audio_available"] is True
    play = client.get(f"{url}/session-01/segment-01/audio")
    assert play.content == content
    assert play.headers["cache-control"] == "no-store"
    partial = client.get(f"{url}/session-01/segment-01/audio", headers={"Range": "bytes=0-43"})
    assert partial.status_code == 206
    assert partial.content == content[:44]
    assert (
        client.post(f"{url}/session-01/audio", content=content, headers={"Content-Type": "audio/wav"}).status_code
        == 409
    )
    for username in ["teacher-02", "student-01", "parent-01", "admin-01"]:
        login(client, username)
        assert client.get(f"{url}/session-01/segment-01/audio").status_code == 403
        assert (
            client.post(f"{url}/session-01/audio", content=content, headers={"Content-Type": "audio/wav"}).status_code
            == 403
        )


def test_invalid_audio_not_saved(classroom_api: tuple[TestClient, str], event: SpeechEvent) -> None:
    client, url = classroom_api
    client.post(f"{url}/events", content=event.model_dump_json())
    assert (
        client.post(f"{url}/session-01/audio", content=b"not wav", headers={"Content-Type": "audio/wav"}).status_code
        == 422
    )
    assert (
        client.post(f"{url}/session-01/audio", content=b"not wav", headers={"Content-Type": "text/plain"}).status_code
        == 415
    )
    assert client.get(f"{url}/timeline").json()[0]["audio_available"] is False


PASSWORD = "speech-api-test-credentials"


def login(client: TestClient, username: str = "teacher-01") -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200


@pytest.fixture
def classroom_api(tmp_path: Path) -> Iterator[tuple[TestClient, str]]:
    database = tmp_path / "speech-api.sqlite3"
    app = create_app(database, AuthSettings(demo_password=SecretStr(PASSWORD)))
    request = CreateClassroom(
        title="平均分",
        date=date(2026, 10, 31),
        objective="理解平均分条件",
        students=["student-01", "student-02"],
        questions=[Question(id="q-01", text="四块都算四分之一吗？", reference_answer="必须平均分")],
        source="合成教学事件",
        authorization="不包含真实学生信息",
        idempotency_key="speech-test-01",
    )
    with TestClient(app, headers={"Content-Type": "application/json"}) as client:
        login(client)
        response = client.post("/api/classrooms", content=request.model_dump_json())
        assert response.status_code == 201
        classroom = Classroom.model_validate_json(response.content)
        yield client, f"/api/classrooms/{classroom.id}/speech"


@pytest.fixture
def event() -> SpeechEvent:
    return SpeechEvent(
        session_id="session-01",
        event_id="event-01",
        sequence=1,
        event_type="final",
        source_kind="synthetic",
        segment_id="segment-01",
        revision=1,
        start_ms=10,
        end_ms=500,
        text="分成四块就都是四分之一",
        source_ref="position-A",
    )


def review_payload(**changes: str | int) -> ReviewRequest:
    return ReviewRequest.model_validate(
        {
            "expected_version": 1,
            "student_alias": "student-01",
            "question_id": "q-01",
            "text_review": "confirmed",
            "identity_review": "confirmed",
            "question_review": "confirmed",
        }
        | changes
    )


def test_event_review_and_unavailable_audio(
    classroom_api: tuple[TestClient, str],
    event: SpeechEvent,
) -> None:
    client, url = classroom_api
    response = client.post(f"{url}/events", content=event.model_dump_json())
    assert EventReceipt.model_validate_json(response.content).created is True
    duplicate = client.post(f"{url}/events", content=event.model_dump_json())
    assert EventReceipt.model_validate_json(duplicate.content).created is False
    events = TypeAdapter(list[SpeechEvent]).validate_json(client.get(f"{url}/events").content)
    assert events == [event]
    timeline = TypeAdapter(list[Utterance]).validate_json(client.get(f"{url}/timeline").content)
    assert len(timeline) == 1
    assert timeline[0].student_alias is None
    assert timeline[0].identity_review == "pending"
    response = client.put(f"{url}/session-01/segment-01/review", content=review_payload().model_dump_json())
    assert response.status_code == 200
    reviewed = Utterance.model_validate_json(response.content)
    assert reviewed.reviewed_by == "teacher-01"
    assert reviewed.version == 2
    assert reviewed.identity_review == "confirmed"
    assert client.get(f"{url}/session-01/segment-01/audio").status_code == 404
    assert client.get(f"{url}/session-01/absent/audio").status_code == 404


def test_source_and_event_content_cannot_be_forged(
    classroom_api: tuple[TestClient, str],
    event: SpeechEvent,
) -> None:
    client, url = classroom_api
    live = event.model_copy(update={"source_kind": "upstream_live"})
    assert client.post(f"{url}/events", content=live.model_dump_json()).status_code == 409
    assert client.post(f"{url}/events", content=event.model_dump_json()).status_code == 200
    changed = event.model_copy(update={"text": "同一个标识，另一段内容"})
    assert client.post(f"{url}/events", content=changed.model_dump_json()).status_code == 409
    events = TypeAdapter(list[SpeechEvent]).validate_json(client.get(f"{url}/events").content)
    assert events == [event]


def test_partial_cannot_be_confirmed(classroom_api: tuple[TestClient, str], event: SpeechEvent) -> None:
    client, url = classroom_api
    partial = event.model_copy(update={"event_type": "partial"})
    assert client.post(f"{url}/events", content=partial.model_dump_json()).status_code == 200
    assert (
        client.put(
            f"{url}/session-01/segment-01/review",
            content=review_payload().model_dump_json(),
        ).status_code
        == 409
    )


def test_review_rejects_foreign_student_and_question(
    classroom_api: tuple[TestClient, str],
    event: SpeechEvent,
) -> None:
    client, url = classroom_api
    assert client.post(f"{url}/events", content=event.model_dump_json()).status_code == 200
    for request in [review_payload(student_alias="student-03"), review_payload(question_id="foreign-question")]:
        assert (
            client.put(
                f"{url}/session-01/segment-01/review",
                content=request.model_dump_json(),
            ).status_code
            == 422
        )
    assert (
        client.put(
            f"{url}/session-01/missing/review",
            content=review_payload().model_dump_json(),
        ).status_code
        == 404
    )


def test_teacher_ownership_and_other_roles_protect_every_route(
    classroom_api: tuple[TestClient, str],
    event: SpeechEvent,
) -> None:
    client, url = classroom_api
    assert client.post(f"{url}/events", content=event.model_dump_json()).status_code == 200
    for username in ("teacher-02", "student-01", "parent-01", "admin-01"):
        login(client, username)
        assert client.get(f"{url}/events").status_code == 403
        assert client.get(f"{url}/timeline").status_code == 403
        assert client.get(f"{url}/session-01/segment-01/audio").status_code == 403
        assert client.post(f"{url}/events", content=event.model_dump_json()).status_code == 403
        assert (
            client.put(
                f"{url}/session-01/segment-01/review",
                content=review_payload().model_dump_json(),
            ).status_code
            == 403
        )
