from dataclasses import dataclass

import httpx
import pytest
from pydantic import TypeAdapter
from test_evidence import environment as environment
from test_evidence import model_response as model_response
from test_exercises import ExerciseEnvironment, ResponseInstaller, output
from test_exercises import control as control
from test_exercises import ready as ready

from teaching.plans.models import GeneratePlan, PlanContent, PlanGenerationResult, PlanRecord


@dataclass
class PlanEnvironment:
    ready: ExerciseEnvironment

    @property
    def url(self) -> str:
        return f"/api/classrooms/{self.ready.env.cid}/plans"

    def generate(self, key: str = "plan-request-01") -> httpx.Response:
        return self.ready.env.client.post(
            f"{self.url}/generate",
            content=GeneratePlan(
                evidence_id=self.ready.evidence.id,
                expected_evidence_revision=2,
                idempotency_key=key,
            ).model_dump_json(),
        )

    def complete(self, record: PlanRecord) -> httpx.Response:
        content = record.content.model_copy(
            update={
                "preparation": "先让学生独立比较面积",
                "alternative": "若无法解释则提供平均分示例",
                "keep_content": "保留分数表示整体与部分的练习",
            }
        )
        return self.ready.env.client.put(
            f"{self.url}/{record.id}/review",
            json={
                "expected_revision": record.revision,
                "action": "confirmed",
                "content": content.model_dump(),
            },
        )


@pytest.fixture
def planning(ready: ExerciseEnvironment) -> PlanEnvironment:
    return PlanEnvironment(ready)


def test_missing_fields_then_confirm_adopt_and_record_observations(
    planning: PlanEnvironment,
    control: ResponseInstaller,
) -> None:
    calls: list[httpx.Request] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert "教师确认需比较面积相等条件" in request.content.decode()
        return output()

    control(response)
    result = PlanGenerationResult.model_validate_json(planning.generate().content)
    record = result.plan
    assert record.content.preparation == record.content.alternative == record.content.keep_content == ""
    assert record.content.target_student == "student-01"
    assert record.content.question == "为何平均分？"
    assert PlanGenerationResult.model_validate_json(planning.generate().content).plan.id == record.id
    assert len(calls) == 1
    endpoint = f"{planning.url}/{record.id}"
    client = planning.ready.env.client
    assert client.put(f"{endpoint}/review", json={"expected_revision": 1, "action": "confirmed"}).status_code == 422
    assert client.put(f"{endpoint}/adoption", json={"expected_revision": 1, "adopted": True}).status_code == 409
    confirmed = PlanRecord.model_validate_json(planning.complete(record).content)
    assert confirmed.status == "confirmed"
    assert confirmed.content.preparation == "先让学生独立比较面积"
    assert confirmed.original.content.classroom_question == "为何平均分？"
    response = client.put(
        f"{endpoint}/adoption",
        json={
            "expected_revision": 2,
            "adopted": True,
            "observation": "已使用比较面积活动，下一次检查迁移",
        },
    )
    adopted = PlanRecord.model_validate_json(response.content)
    assert adopted.adopted is True
    assert adopted.observations[0].teacher == "teacher-01"
    revoked = client.put(f"{endpoint}/adoption", json={"expected_revision": 3, "adopted": False})
    assert PlanRecord.model_validate_json(revoked.content).adopted is False
    assert len(PlanRecord.model_validate_json(revoked.content).observations) == 1


def test_changed_basis_clears_adoption_preserves_teacher_content(
    planning: PlanEnvironment,
    control: ResponseInstaller,
) -> None:
    control(lambda request: output())
    record = PlanGenerationResult.model_validate_json(planning.generate().content).plan
    planning.complete(record)
    endpoint = f"{planning.url}/{record.id}"
    client = planning.ready.env.client
    client.put(f"{endpoint}/adoption", json={"expected_revision": 2, "adopted": True})
    planning.ready.env.verify(2, "student-02")
    listing = TypeAdapter(list[PlanGenerationResult]).validate_json(client.get(planning.url).content)
    assert listing[0].plan.status == "stale"
    assert listing[0].plan.adopted is False
    assert listing[0].plan.content.preparation == "先让学生独立比较面积"
    assert client.put(f"{endpoint}/adoption", json={"expected_revision": 3, "adopted": True}).status_code == 409


def test_old_return_is_audited_without_creating_plan(planning: PlanEnvironment, control: ResponseInstaller) -> None:
    def response(request: httpx.Request) -> httpx.Response:
        planning.ready.review_evidence()
        return output()

    control(response)
    result = PlanGenerationResult.model_validate_json(planning.generate().content)
    assert result.task.status == "stale"
    assert result.task.discarded_draft is not None
    assert result.plan is None


def test_generation_failure_preserves_existing_manual_plan(
    planning: PlanEnvironment,
    control: ResponseInstaller,
) -> None:
    control(lambda request: output())
    record = PlanGenerationResult.model_validate_json(planning.generate().content).plan
    planning.complete(record)
    calls: list[int] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, text="private upstream response")

    control(response)
    result = PlanGenerationResult.model_validate_json(planning.generate("plan-request-fail").content)
    again = PlanGenerationResult.model_validate_json(planning.generate("plan-request-fail").content)
    assert result.task.status == again.task.status == "failed"
    assert result.plan is None
    assert len(calls) == 1
    listing = TypeAdapter(list[PlanGenerationResult]).validate_json(planning.ready.env.client.get(planning.url).content)
    assert listing[0].plan.status == "confirmed"
    assert listing[0].plan.content.alternative == "若无法解释则提供平均分示例"


def test_unauthorized_and_changed_target_are_rejected(planning: PlanEnvironment, control: ResponseInstaller) -> None:
    control(lambda request: output())
    record = PlanGenerationResult.model_validate_json(planning.generate().content).plan
    content = PlanContent.model_validate(record.content.model_dump() | {"target_student": "student-02"})
    client = planning.ready.env.client
    assert (
        client.put(
            f"{planning.url}/{record.id}/review",
            json={
                "expected_revision": 1,
                "action": "rejected",
                "content": content.model_dump(),
            },
        ).status_code
        == 422
    )
    for username in ("teacher-02", "parent-01"):
        client.post("/api/auth/login", json={"username": username, "password": "evidence-test-password"})
        assert planning.generate().status_code == 403
        assert client.get(planning.url).status_code == 403


def test_rejected_evidence_cannot_generate(planning: PlanEnvironment, control: ResponseInstaller) -> None:
    calls: list[int] = []

    def response(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return output()

    control(response)
    planning.ready.review_evidence()
    assert planning.generate().status_code == 409
    assert calls == []
