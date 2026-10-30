import pytest
from pydantic import TypeAdapter
from test_evidence import Environment
from test_evidence import environment as environment

from teaching.audio.models import SpeechEvent, Utterance
from teaching.audio.store import SpeechStore
from teaching.deletion.models import DeleteClassroom
from teaching.deletion.store import DeletionStore
from teaching.integration.models import SpeechEndpointStatus, SpeechIngest, SpeechReceipt

TOKEN = "synthetic-test-ingest-credential-0123456789"


@pytest.fixture
def connected(environment: Environment) -> Environment:
    return environment


def payload(env: Environment, source: str = "upstream_live") -> SpeechIngest:
    return SpeechIngest.model_validate(
        {
            "classroom_id": env.cid,
            "event": env.event.model_dump() | {"event_id": "trusted-event-01", "revision": 2, "source_kind": source},
        }
    )


@pytest.mark.parametrize("token", [None, "short"])
def test_unconfigured_endpoint_is_unavailable(
    connected: Environment,
    monkeypatch: pytest.MonkeyPatch,
    token: str | None,
) -> None:
    if token is None:
        monkeypatch.delenv("SPEECH_INGEST_TOKEN", raising=False)
    else:
        monkeypatch.setenv("SPEECH_INGEST_TOKEN", token)
    response = connected.client.post("/api/integrations/speech/events", content=payload(connected).model_dump_json())
    assert response.status_code == 503
    status = SpeechEndpointStatus.model_validate_json(connected.client.get("/api/integrations/speech/status").content)
    assert status.endpoint_enabled is False


def test_token_required_even_with_teacher_cookie(connected: Environment, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPEECH_INGEST_TOKEN", TOKEN)
    for headers in ({}, {"Authorization": "Bearer wrong-token"}, {"Authorization": f"Basic {TOKEN}"}):
        response = connected.client.post(
            "/api/integrations/speech/events",
            content=payload(connected).model_dump_json(),
            headers=headers,
        )
        assert response.status_code == 401
        assert TOKEN not in response.text
    response = connected.client.post(
        f"/api/classrooms/{connected.cid}/speech/events",
        content=payload(connected).event.model_dump_json(),
    )
    assert response.status_code == 409


@pytest.mark.parametrize("source", ["upstream_live", "recorded_result"])
def test_trusted_event_is_idempotent_and_not_teacher_confirmed(
    connected: Environment,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    monkeypatch.setenv("SPEECH_INGEST_TOKEN", TOKEN)
    body = payload(connected, source)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = connected.client.post("/api/integrations/speech/events", content=body.model_dump_json(), headers=headers)
    assert response.status_code == 200
    assert SpeechReceipt.model_validate_json(response.content).created is True
    response = connected.client.post("/api/integrations/speech/events", content=body.model_dump_json(), headers=headers)
    assert SpeechReceipt.model_validate_json(response.content).created is False
    conflict = body.model_copy(update={"event": body.event.model_copy(update={"text": "同标识不同内容"})})
    assert (
        connected.client.post(
            "/api/integrations/speech/events",
            content=conflict.model_dump_json(),
            headers=headers,
        ).status_code
        == 409
    )
    timeline = TypeAdapter(list[Utterance]).validate_json(
        connected.client.get(f"/api/classrooms/{connected.cid}/speech/timeline").content,
    )
    assert timeline[0].source_kind == source
    assert timeline[0].student_alias is None
    assert (timeline[0].text_review, timeline[0].identity_review, timeline[0].question_review) == (
        "pending",
        "pending",
        "pending",
    )
    connected.client.post("/api/auth/logout")
    assert connected.client.get(f"/api/classrooms/{connected.cid}", headers=headers).status_code == 401
    assert connected.client.get("/api/integrations/speech/status", headers=headers).status_code == 401


def test_status_only_exposes_endpoint_configuration(connected: Environment, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPEECH_INGEST_TOKEN", TOKEN)
    response = connected.client.get("/api/integrations/speech/status")
    status = SpeechEndpointStatus.model_validate_json(response.content)
    assert status.endpoint_enabled is True
    assert status.protocol_version == "app-draft-1"
    assert "不代表" in status.message
    assert TOKEN not in response.text
    connected.client.post("/api/auth/login", json={"username": "parent-01", "password": "evidence-test-password"})
    assert connected.client.get("/api/integrations/speech/status").status_code == 403


def test_synthetic_or_missing_classroom_cannot_enter(connected: Environment, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPEECH_INGEST_TOKEN", TOKEN)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert (
        connected.client.post(
            "/api/integrations/speech/events",
            content=payload(connected, "synthetic").model_dump_json(),
            headers=headers,
        ).status_code
        == 409
    )
    body = payload(connected).model_copy(update={"classroom_id": "absent"})
    assert (
        connected.client.post(
            "/api/integrations/speech/events",
            content=body.model_dump_json(),
            headers=headers,
        ).status_code
        == 404
    )
    current = connected.store.get_classroom("teacher-01", connected.cid)
    DeletionStore(connected.store).create(
        connected.cid,
        "teacher-01",
        DeleteClassroom(
            expected_revision=current.revision,
            confirmation=current.title,
            idempotency_key="delete-before-ingest",
        ),
    )
    assert (
        connected.client.post(
            "/api/integrations/speech/events",
            content=payload(connected).model_dump_json(),
            headers=headers,
        ).status_code
        == 404
    )
    assert connected.speech.events(connected.cid) == []


def test_deletion_after_endpoint_check_still_rejected(
    connected: Environment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPEECH_INGEST_TOKEN", TOKEN)
    speech: SpeechStore = connected.client.app.state.speech
    original = speech.receive

    def late(classroom: str, event: SpeechEvent) -> bool:
        current = connected.store.get_classroom("teacher-01", classroom)
        DeletionStore(connected.store).create(
            classroom,
            "teacher-01",
            DeleteClassroom(
                expected_revision=current.revision,
                confirmation=current.title,
                idempotency_key="delete-during-ingest",
            ),
        )
        return original(classroom, event)

    monkeypatch.setattr(speech, "receive", late)
    response = connected.client.post(
        "/api/integrations/speech/events",
        content=payload(connected).model_dump_json(),
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 410
    assert connected.speech.events(connected.cid) == []
