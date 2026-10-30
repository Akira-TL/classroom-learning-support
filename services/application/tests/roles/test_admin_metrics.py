from typing import Literal

import httpx
from test_admin import Overview
from test_admin import environment as environment
from test_admin import model_response as model_response
from test_admin import overview as overview
from test_exercises import ResponseInstaller
from test_exercises import control as control
from test_exercises import output as support_output

from teaching.manual_exercises.models import CreateManualExercises, ManualExerciseRecord
from teaching.models import Exercise
from teaching.plans.models import PlanGenerationResult


def test_generation_confirmation_and_adoption_have_explicit_denominators(
    overview: Overview, control: ResponseInstaller
) -> None:
    evidence = overview.evidence(1, "student-01")
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return support_output()

    control(respond)
    client = overview.env.client
    url = f"/api/classrooms/{overview.env.cid}/plans"
    body = {"evidence_id": evidence.id, "expected_evidence_revision": 2, "idempotency_key": "metrics-plan-01"}
    first = PlanGenerationResult.model_validate_json(client.post(f"{url}/generate", json=body).content).plan
    again = PlanGenerationResult.model_validate_json(client.post(f"{url}/generate", json=body).content).plan
    assert first is not None and again.id == first.id
    second = PlanGenerationResult.model_validate_json(
        client.post(
            f"{url}/generate",
            json=body | {"idempotency_key": "metrics-plan-02"},
        ).content
    ).plan
    assert second is not None and len(calls) == 2
    summary = overview.summary()
    assert summary.plan_metrics.generated_count == 2
    assert summary.plan_metrics.confirmed_count == summary.plan_metrics.adopted_count == 0
    assert summary.plan_metrics.confirmation_rate.numerator == 0
    assert summary.plan_metrics.confirmation_rate.denominator == 2
    assert summary.plan_metrics.confirmation_rate.ratio == 0
    assert summary.plan_metrics.adoption_rate.denominator == 0
    assert summary.plan_metrics.adoption_rate.ratio is None
    assert summary.observed_student_count is None and summary.hidden
    overview.login("teacher-01")
    completed = first.content.model_copy(
        update={
            "preparation": "先比较面积",
            "alternative": "用纸片演示",
            "keep_content": "保留平均分复习",
        }
    )
    assert (
        client.put(
            f"{url}/{first.id}/review",
            json={
                "expected_revision": 1,
                "action": "confirmed",
                "content": completed.model_dump(),
            },
        ).status_code
        == 200
    )
    assert client.put(f"{url}/{first.id}/adoption", json={"expected_revision": 2, "adopted": True}).status_code == 200
    assert (
        client.put(f"{url}/{second.id}/review", json={"expected_revision": 1, "action": "rejected"}).status_code == 200
    )
    control(lambda request: httpx.Response(503))
    failed = PlanGenerationResult.model_validate_json(
        client.post(
            f"{url}/generate",
            json=body | {"idempotency_key": "metrics-plan-fail"},
        ).content
    )
    assert failed.task.status == "failed" and failed.plan is None
    summary = overview.summary()
    assert summary.plan_metrics.generated_count == 2
    assert summary.plan_metrics.confirmed_count == summary.plan_metrics.adopted_count == 1
    assert summary.plan_metrics.confirmation_rate.ratio == 0.5
    assert summary.plan_metrics.confirmation_rate.numerator == 1
    assert summary.plan_metrics.confirmation_rate.denominator == 2
    assert summary.plan_metrics.adoption_rate.ratio == 1
    assert summary.exercise_metrics.generated_count == 0


def test_manual_general_exercises_are_a_separate_source_and_resource_need(overview: Overview) -> None:
    overview.login("teacher-01")
    levels: tuple[Literal["concept", "explanation", "transfer"], ...] = ("concept", "explanation", "transfer")
    request = CreateManualExercises(
        idempotency_key="metrics-manual-01",
        exercises=[
            Exercise(
                level=level, question="把整体平均分成四份，每份占多少？", answer="四分之一", explanation="四份相等"
            )
            for level in levels
        ],
    )
    client = overview.env.client
    url = f"/api/classrooms/{overview.env.cid}/manual-exercises"
    record = ManualExerciseRecord.model_validate_json(client.post(url, content=request.model_dump_json()).content)
    assert (
        ManualExerciseRecord.model_validate_json(
            client.post(url, content=request.model_dump_json()).content,
        ).id
        == record.id
    )
    summary = overview.summary()
    assert summary.manual_exercise_metrics.recorded_count == 1
    assert summary.manual_exercise_metrics.source == "teacher_manual_general"
    assert summary.manual_exercise_metrics.confirmation_rate.denominator == 1
    assert summary.manual_exercise_metrics.confirmed_count == summary.manual_exercise_metrics.adopted_count == 0
    assert summary.exercise_metrics.generated_count == summary.exercise_metrics.adopted_count == 0
    assert summary.performance_state == "no_data"
    overview.login("teacher-01")
    assert (
        client.put(f"{url}/{record.id}/review", json={"expected_revision": 1, "action": "confirmed"}).status_code == 200
    )
    assert client.put(f"{url}/{record.id}/adoption", json={"expected_revision": 2, "adopted": True}).status_code == 200
    summary = overview.summary()
    assert summary.manual_exercise_metrics.confirmed_count == summary.manual_exercise_metrics.adopted_count == 1
    assert summary.manual_exercise_metrics.adoption_rate.ratio == 1
    assert [item.count for item in summary.resource_needs] == [0, 0, 1]
    overview.login("teacher-01")
    assert (
        client.put(f"{url}/{record.id}/review", json={"expected_revision": 3, "action": "rejected"}).status_code == 200
    )
    summary = overview.summary()
    assert summary.manual_exercise_metrics.recorded_count == 1
    assert summary.manual_exercise_metrics.confirmed_count == summary.manual_exercise_metrics.adopted_count == 0
    assert summary.manual_exercise_metrics.adoption_rate.denominator == 0
    assert summary.manual_exercise_metrics.adoption_rate.ratio is None
    assert [item.count for item in summary.resource_needs] == [0, 0, 0]
