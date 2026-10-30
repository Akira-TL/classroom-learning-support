from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, TypeAdapter

from teaching.api import create_app
from teaching.audio.models import SpeechEvent
from teaching.classroom.auth import AuthSettings
from teaching.classroom.classrooms import Classroom, CreateClassroom, Question

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


def test_timeline_permissions(classroom_api: tuple[TestClient, str], event: SpeechEvent) -> None:
    client, url = classroom_api
    assert client.post(f"{url}/events", content=event.model_dump_json()).status_code == 200
    assert len(client.get(f"{url}/timeline").json()) == 1
    for username in ("teacher-02", "student-01", "parent-01", "admin-01"):
        login(client, username)
        assert client.get(f"{url}/events").status_code == 403
        assert client.get(f"{url}/timeline").status_code == 403
        assert client.post(f"{url}/events", content=event.model_dump_json()).status_code == 403
