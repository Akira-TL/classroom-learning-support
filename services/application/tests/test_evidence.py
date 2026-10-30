import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, TypeAdapter

from teaching.api import create_app
from teaching.audio.models import ReviewRequest, SpeechEvent
from teaching.audio.store import SpeechStore
from teaching.classroom.auth import AuthSettings
from teaching.classroom.classrooms import CreateClassroom, Question, UpdateClassroom
from teaching.classroom.storage import SQLiteStore, StoreError
from teaching.deepseek import DeepSeek
from teaching.learning.models import EvidenceRecord, EvidenceReview, GenerateEvidence, GenerationResult
from teaching.learning.store import EvidenceStore

PASSWORD = "evidence-test-password"
QUOTE = "分成四块就都是四分之一"


def test_confirmed_evidence_gate_checks_within_transaction(
    environment: "Environment",
    model_response: list[httpx.Request],
) -> None:
    environment.verify()
    result = GenerationResult.model_validate_json(environment.generate().content)
    record = result.evidence
    gate = EvidenceStore(environment.store)
    with environment.store.connection() as db, pytest.raises(StoreError, match="已确认证据"):
        gate.require_confirmed(db, environment.cid, "teacher-01", record.id, record.revision)
    response = environment.client.put(
        f"{environment.url}/{record.id}/review",
        content=EvidenceReview(expected_revision=record.revision, action="confirmed").model_dump_json(),
    )
    confirmed = EvidenceRecord.model_validate_json(response.content)
    with environment.store.connection() as db:
        current = gate.require_confirmed(db, environment.cid, "teacher-01", confirmed.id, confirmed.revision)
        assert current.status == "confirmed"
    with environment.store.connection() as db, pytest.raises(StoreError, match="无权"):
        gate.require_confirmed(db, environment.cid, "teacher-02", confirmed.id, confirmed.revision)
    environment.verify(2, "student-02")
    with environment.store.connection() as db, pytest.raises(StoreError, match="已确认证据"):
        gate.require_confirmed(db, environment.cid, "teacher-01", confirmed.id, confirmed.revision)


@dataclass
class Environment:
    client: TestClient
    store: SQLiteStore
    speech: SpeechStore
    cid: str
    event: SpeechEvent

    @property
    def url(self) -> str:
        return f"/api/classrooms/{self.cid}/evidence"

    def verify(self, version: int = 1, student: str = "student-01") -> None:
        self.speech.review(
            self.cid,
            "s-1",
            "u-1",
            "teacher-01",
            ReviewRequest(
                expected_version=version,
                student_alias=student,
                question_id="q-1",
                text_review="confirmed",
                identity_review="confirmed",
                question_review="confirmed",
            ),
        )

    def generate(self, key: str = "generate-01", version: int = 2) -> httpx.Response:
        return self.client.post(
            f"{self.url}/generate",
            content=GenerateEvidence(
                session_id="s-1",
                segment_id="u-1",
                expected_version=version,
                idempotency_key=key,
            ).model_dump_json(),
        )


@pytest.fixture
def environment(tmp_path: Path) -> Iterator[Environment]:
    path = tmp_path / "learning.sqlite3"
    app = create_app(path, AuthSettings(demo_password=SecretStr(PASSWORD)))
    speech = SpeechStore(path)
    classroom = app.state.store.create_classroom(
        "teacher-01",
        CreateClassroom(
            title="分数",
            date=date(2026, 10, 31),
            objective="理解平均分",
            students=["student-01", "student-02"],
            questions=[Question(id="q-1", text="四块就是四分之一吗？", reference_answer="需要平均分")],
            source="synthetic",
            authorization="合成教学数据",
            idempotency_key="classroom-01",
        ),
    )
    event = SpeechEvent(
        session_id="s-1",
        event_id="e-1",
        sequence=1,
        event_type="final",
        source_kind="synthetic",
        segment_id="u-1",
        text=QUOTE,
    )
    speech.receive(classroom.id, event)
    with TestClient(app, headers={"Content-Type": "application/json"}) as client:
        assert client.post("/api/auth/login", json={"username": "teacher-01", "password": PASSWORD}).status_code == 200
        yield Environment(client, app.state.store, speech, classroom.id, event)


@pytest.fixture
def model_response(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.host == "api.deepseek.com"
        return output()

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        monkeypatch.setattr(
            DeepSeek, "from_environment", classmethod(lambda cls, unused: DeepSeek(client, "test-secret"))
        )
        yield calls


def output() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "quote": QUOTE,
                                "interpretation": "需要核实平均分条件",
                                "limitation": "单次回答不足以判断稳定掌握",
                                "follow_up_question": "四块是否一样大？",
                            },
                            ensure_ascii=False,
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        },
    )


def test_unverified_is_rejected_without_model_call(
    environment: Environment, model_response: list[httpx.Request]
) -> None:
    assert environment.generate(version=1).status_code == 409
    assert model_response == []


def test_generation_reference_review_and_idempotency(
    environment: Environment,
    model_response: list[httpx.Request],
) -> None:
    environment.verify()
    result = GenerationResult.model_validate_json(environment.generate().content)
    assert result.task.status == "succeeded"
    assert result.evidence.basis.context.utterance_revision == 2
    assert result.evidence.content.quote == QUOTE
    duplicate = GenerationResult.model_validate_json(environment.generate().content)
    assert duplicate.evidence.id == result.evidence.id
    assert len(model_response) == 1
    request = EvidenceReview(expected_revision=1, action="confirmed")
    response = environment.client.put(
        f"{environment.url}/{result.evidence.id}/review", content=request.model_dump_json()
    )
    reviewed = EvidenceRecord.model_validate_json(response.content)
    assert reviewed.status == "confirmed"
    assert reviewed.reviewed_by == "teacher-01"
    rejected = EvidenceReview(expected_revision=2, action="rejected")
    response = environment.client.put(
        f"{environment.url}/{result.evidence.id}/review", content=rejected.model_dump_json()
    )
    assert EvidenceRecord.model_validate_json(response.content).status == "rejected"


def test_identity_change_invalidates_evidence_without_erasing_edits(
    environment: Environment,
    model_response: list[httpx.Request],
) -> None:
    environment.verify()
    result = GenerationResult.model_validate_json(environment.generate().content)
    edited = result.evidence.content.model_copy(update={"interpretation": "教师补充的解释"})
    review = EvidenceReview(expected_revision=1, action="confirmed", content=edited)
    assert (
        environment.client.put(
            f"{environment.url}/{result.evidence.id}/review",
            content=review.model_dump_json(),
        ).status_code
        == 200
    )
    environment.verify(2, "student-02")
    listing = TypeAdapter(list[GenerationResult]).validate_json(environment.client.get(environment.url).content)
    assert listing[0].evidence.status == "stale"
    assert listing[0].evidence.content.interpretation == "教师补充的解释"
    assert listing[0].evidence.original.content.interpretation == "需要核实平均分条件"
    assert (
        environment.client.put(
            f"{environment.url}/{result.evidence.id}/review",
            content=review.model_dump_json(),
        ).status_code
        == 409
    )


def test_revision_during_generation_discards_return_and_records_audit(
    environment: Environment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment.verify()

    def transport(request: httpx.Request) -> httpx.Response:
        environment.speech.receive(
            environment.cid,
            environment.event.model_copy(
                update={
                    "event_id": "e-2",
                    "revision": 2,
                    "event_type": "revision",
                    "text": "我需要再比较大小",
                    "sequence": 2,
                }
            ),
        )
        return output()

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        monkeypatch.setattr(
            DeepSeek, "from_environment", classmethod(lambda cls, unused: DeepSeek(client, "test-secret"))
        )
        result = GenerationResult.model_validate_json(environment.generate().content)
    assert result.task.status == "stale"
    assert result.evidence is None
    assert result.task.discarded_draft.content.quote == QUOTE
    listing = TypeAdapter(list[GenerationResult]).validate_json(environment.client.get(environment.url).content)
    assert listing[0].task.status == "stale"


def test_context_changes_are_selective(environment: Environment, model_response: list[httpx.Request]) -> None:
    environment.verify()
    result = GenerationResult.model_validate_json(environment.generate().content)
    original = environment.store.get_classroom("teacher-01", environment.cid)
    environment.store.update_classroom(
        "teacher-01",
        environment.cid,
        UpdateClassroom(
            **original.model_dump(exclude={"id", "teacher_id", "revision"}) | {"title": "只改标题"},
            expected_revision=1,
        ),
    )
    listing = TypeAdapter(list[GenerationResult]).validate_json(environment.client.get(environment.url).content)
    assert listing[0].evidence.status == "pending"
    current = environment.store.get_classroom("teacher-01", environment.cid)
    environment.store.update_classroom(
        "teacher-01",
        environment.cid,
        UpdateClassroom(
            **current.model_dump(exclude={"id", "teacher_id", "revision"}) | {"objective": "新的教学目标"},
            expected_revision=2,
        ),
    )
    listing = TypeAdapter(list[GenerationResult]).validate_json(environment.client.get(environment.url).content)
    assert listing[0].evidence.id == result.evidence.id
    assert listing[0].evidence.status == "stale"


def test_missing_diagram_and_unauthorized_requests(
    environment: Environment,
    model_response: list[httpx.Request],
) -> None:
    environment.verify()
    original = environment.store.get_classroom("teacher-01", environment.cid)
    environment.store.update_classroom(
        "teacher-01",
        environment.cid,
        UpdateClassroom(
            **original.model_dump(exclude={"id", "teacher_id", "revision", "questions"}),
            expected_revision=1,
            questions=[original.questions[0].model_copy(update={"diagram_required": True})],
        ),
    )
    assert environment.generate().status_code == 422
    assert model_response == []
    for name in ("teacher-02", "student-01", "parent-01"):
        environment.client.post("/api/auth/login", json={"username": name, "password": PASSWORD})
        assert environment.generate().status_code == 403
        assert environment.client.get(environment.url).status_code == 403


def test_failed_request_persists_without_retrying_key(
    environment: Environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment.verify()
    calls: list[int] = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, text="do not expose provider response")

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        monkeypatch.setattr(
            DeepSeek, "from_environment", classmethod(lambda cls, unused: DeepSeek(client, "test-secret"))
        )
        first = GenerationResult.model_validate_json(environment.generate().content)
        second = GenerationResult.model_validate_json(environment.generate().content)
    assert first.task.status == second.task.status == "failed"
    assert first.evidence is None
    assert len(calls) == 1
    assert "do not expose" not in first.task.error
