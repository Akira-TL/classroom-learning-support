import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import httpx
import pytest
from pydantic import TypeAdapter
from test_evidence import Environment
from test_evidence import environment as environment
from test_evidence import model_response as model_response

from teaching.deepseek import DeepSeek
from teaching.exercises.models import ExerciseGenerationResult, ExerciseRecord, GenerateExercises
from teaching.learning.models import EvidenceRecord, EvidenceReview, GenerationResult

ResponseInstaller = Callable[[Callable[[httpx.Request], httpx.Response]], None]


@dataclass
class ExerciseEnvironment:
    env: Environment
    evidence: EvidenceRecord

    @property
    def url(self) -> str:
        return f"/api/classrooms/{self.env.cid}/exercises"

    def generate(self, key: str = "exercise-01", revision: int = 2) -> httpx.Response:
        return self.env.client.post(
            f"{self.url}/generate",
            content=GenerateExercises(
                evidence_id=self.evidence.id,
                expected_evidence_revision=revision,
                idempotency_key=key,
            ).model_dump_json(),
        )

    def review_evidence(self, action: str = "rejected") -> None:
        response = self.env.client.put(
            f"{self.env.url}/{self.evidence.id}/review",
            json={
                "expected_revision": 2,
                "action": action,
            },
        )
        assert response.status_code == 200


@pytest.fixture
def ready(environment: Environment, model_response: list[httpx.Request]) -> ExerciseEnvironment:
    environment.verify()
    result = GenerationResult.model_validate_json(environment.generate().content)
    edited = result.evidence.content.model_copy(update={"interpretation": "教师确认需比较面积相等条件"})
    response = environment.client.put(
        f"{environment.url}/{result.evidence.id}/review",
        content=EvidenceReview(
            expected_revision=1,
            action="confirmed",
            content=edited,
        ).model_dump_json(),
    )
    evidence = EvidenceRecord.model_validate_json(response.content)
    return ExerciseEnvironment(environment, evidence)


def output() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "exercises": [
                                    {
                                        "level": level,
                                        "question": "把饼平均分成四份，每份是多少？",
                                        "answer": "四分之一",
                                        "explanation": "四份相等",
                                    }
                                    for level in ("concept", "explanation", "transfer")
                                ],
                                "classroom_question": "为何平均分？",
                                "next_lesson": "对比不等分",
                                "check_method": "用新题检查",
                            },
                            ensure_ascii=False,
                        )
                    },
                    "finish_reason": "stop",
                }
            ]
        },
    )


@pytest.fixture
def control(monkeypatch: pytest.MonkeyPatch) -> Iterator[ResponseInstaller]:
    clients: list[httpx.Client] = []

    def install(handler: Callable[[httpx.Request], httpx.Response]) -> None:
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        monkeypatch.setattr(
            DeepSeek, "from_environment", classmethod(lambda cls, unused: DeepSeek(client, "test-secret"))
        )

    yield install
    for client in clients:
        client.close()


def test_generate_teacher_edits_and_adoption(ready: ExerciseEnvironment, control: ResponseInstaller) -> None:
    calls: list[httpx.Request] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert "教师确认需比较面积相等条件" in request.content.decode()
        return output()

    control(response)
    result = ExerciseGenerationResult.model_validate_json(ready.generate().content)
    record = result.exercise_set
    assert result.task.status == "succeeded"
    assert record.status == "pending"
    assert record.original.evidence.draft.content.interpretation == "教师确认需比较面积相等条件"
    assert ExerciseGenerationResult.model_validate_json(ready.generate().content).exercise_set.id == record.id
    assert len(calls) == 1
    endpoint = f"{ready.url}/{record.id}"
    assert (
        ready.env.client.put(f"{endpoint}/adoption", json={"expected_revision": 1, "adopted": True}).status_code == 409
    )
    exercises = [item.model_copy(update={"answer": "1/4"}) for item in record.exercises]
    response = ready.env.client.put(
        f"{endpoint}/review",
        json={
            "expected_revision": 1,
            "action": "confirmed",
            "exercises": [item.model_dump() for item in exercises],
        },
    )
    edited = ExerciseRecord.model_validate_json(response.content)
    assert edited.exercises[0].answer == "1/4"
    assert edited.original.content.exercises[0].answer == "四分之一"
    adopted = ready.env.client.put(f"{endpoint}/adoption", json={"expected_revision": 2, "adopted": True})
    assert ExerciseRecord.model_validate_json(adopted.content).adopted is True
    withdrawn = ready.env.client.put(f"{endpoint}/adoption", json={"expected_revision": 3, "adopted": False})
    assert ExerciseRecord.model_validate_json(withdrawn.content).adopted is False


def test_rejected_evidence_cannot_generate(ready: ExerciseEnvironment, control: ResponseInstaller) -> None:
    calls: list[int] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return output()

    control(response)
    ready.review_evidence()
    assert ready.generate(revision=3).status_code == 409
    assert calls == []


def test_stale_return_is_audited_without_active_exercises(
    ready: ExerciseEnvironment, control: ResponseInstaller
) -> None:
    def response(request: httpx.Request) -> httpx.Response:
        ready.review_evidence()
        return output()

    control(response)
    result = ExerciseGenerationResult.model_validate_json(ready.generate().content)
    assert result.task.status == "stale"
    assert result.exercise_set is None
    assert result.task.discarded_draft is not None


def test_changed_basis_clears_adoption(ready: ExerciseEnvironment, control: ResponseInstaller) -> None:
    control(lambda request: output())
    record = ExerciseGenerationResult.model_validate_json(ready.generate().content).exercise_set
    endpoint = f"{ready.url}/{record.id}"
    ready.env.client.put(f"{endpoint}/review", json={"expected_revision": 1, "action": "confirmed"})
    ready.env.client.put(f"{endpoint}/adoption", json={"expected_revision": 2, "adopted": True})
    ready.env.verify(2, "student-02")
    listing = TypeAdapter(list[ExerciseGenerationResult]).validate_json(ready.env.client.get(ready.url).content)
    assert listing[0].exercise_set.status == "stale"
    assert listing[0].exercise_set.adopted is False
    assert (
        ready.env.client.put(f"{endpoint}/adoption", json={"expected_revision": 3, "adopted": True}).status_code == 409
    )


def test_failed_request_persists_and_key_cannot_change(ready: ExerciseEnvironment, control: ResponseInstaller) -> None:
    calls: list[int] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, text="private supplier response")

    control(response)
    first = ExerciseGenerationResult.model_validate_json(ready.generate().content)
    second = ExerciseGenerationResult.model_validate_json(ready.generate().content)
    assert first.task.status == second.task.status == "failed"
    assert first.exercise_set is None
    assert "private" not in first.task.error
    assert len(calls) == 1
    assert ready.generate(revision=3).status_code == 409


def test_permissions_and_invalid_levels(ready: ExerciseEnvironment, control: ResponseInstaller) -> None:
    control(lambda request: output())
    record = ExerciseGenerationResult.model_validate_json(ready.generate().content).exercise_set
    invalid = [record.exercises[0].model_dump()] * 3
    assert (
        ready.env.client.put(
            f"{ready.url}/{record.id}/review",
            json={
                "expected_revision": 1,
                "action": "confirmed",
                "exercises": invalid,
            },
        ).status_code
        == 422
    )
    for username in ("teacher-02", "student-01"):
        ready.env.client.post("/api/auth/login", json={"username": username, "password": "evidence-test-password"})
        assert ready.generate().status_code == 403
        assert ready.env.client.get(ready.url).status_code == 403
