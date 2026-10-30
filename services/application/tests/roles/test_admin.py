from dataclasses import dataclass

import httpx
import pytest
from test_evidence import PASSWORD, QUOTE, Environment
from test_evidence import environment as environment
from test_evidence import model_response as model_response
from test_exercises import ResponseInstaller
from test_exercises import control as control
from test_exercises import output as support_output

from teaching.audio.models import ReviewRequest, SpeechEvent
from teaching.classroom.classrooms import CreateClassroom, UpdateClassroom
from teaching.exercises.models import ExerciseGenerationResult, ExerciseRecord
from teaching.learning.models import EvidenceRecord, EvidenceReview, GenerateEvidence, GenerationResult
from teaching.overview.models import AdminSummary
from teaching.plans.models import PlanGenerationResult, PlanRecord


@dataclass
class Overview:
    env: Environment

    def login(self, username: str) -> None:
        assert (
            self.env.client.post("/api/auth/login", json={"username": username, "password": PASSWORD}).status_code
            == 200
        )

    def summary(self) -> AdminSummary:
        self.login("admin-01")
        response = self.env.client.get("/api/admin/summary")
        assert response.status_code == 200
        return AdminSummary.model_validate_json(response.content)

    def evidence(self, index: int, student: str, cid: str | None = None, teacher: str = "teacher-01") -> EvidenceRecord:
        self.login(teacher)
        cid = cid or self.env.cid
        segment = f"u-admin-{index}"
        self.env.speech.receive(
            cid,
            SpeechEvent(
                session_id="s-admin",
                segment_id=segment,
                event_id=f"event-admin-{index}",
                sequence=index,
                event_type="final",
                source_kind="synthetic",
                text=QUOTE,
            ),
        )
        self.env.speech.review(
            cid,
            "s-admin",
            segment,
            teacher,
            ReviewRequest(
                expected_version=1,
                student_alias=student,
                question_id="q-1",
                text_review="confirmed",
                identity_review="confirmed",
                question_review="confirmed",
            ),
        )
        url = f"/api/classrooms/{cid}/evidence"
        response = self.env.client.post(
            f"{url}/generate",
            content=GenerateEvidence(
                session_id="s-admin",
                segment_id=segment,
                expected_version=2,
                idempotency_key=f"admin-evidence-{index}",
            ).model_dump_json(),
        )
        assert response.status_code == 200
        record = GenerationResult.model_validate_json(response.content).evidence
        assert record is not None
        response = self.env.client.put(
            f"{url}/{record.id}/review",
            content=EvidenceReview(
                expected_revision=1,
                action="confirmed",
            ).model_dump_json(),
        )
        assert response.status_code == 200
        return EvidenceRecord.model_validate_json(response.content)


@pytest.fixture
def overview(environment: Environment, model_response: list[httpx.Request]) -> Overview:
    classroom = environment.store.get_classroom("teacher-01", environment.cid)
    environment.store.update_classroom(
        "teacher-01",
        environment.cid,
        UpdateClassroom.model_validate(
            classroom.model_dump(exclude={"id", "teacher_id", "revision"})
            | {"students": [f"student-{number:02d}" for number in range(1, 6)], "expected_revision": 1}
        ),
    )
    return Overview(environment)


def test_role_authorization_empty_state_and_fixed_scope(overview: Overview) -> None:
    client = overview.env.client
    for username in ("teacher-01", "teacher-02", "student-01", "parent-01"):
        overview.login(username)
        assert client.get("/api/admin/summary").status_code == 403
    result = overview.summary()
    assert result.classroom_count == 1
    assert result.performance_state == "no_data"
    assert result.hidden is False
    assert result.confirmed_evidence_count is result.observed_student_count is None
    assert result.adopted_plan_count == result.adopted_exercise_count == result.observation_count == 0
    assert result.plan_metrics.generated_count == result.exercise_metrics.generated_count == 0
    assert result.plan_metrics.confirmation_rate.denominator == 0
    assert result.plan_metrics.confirmation_rate.ratio is None
    assert result.manual_exercise_metrics.recorded_count == 0
    assert result.time_scope == "current_retained_state"
    assert result.snapshot_at.tzinfo is not None
    assert client.get("/api/admin/summary?teacher_id=teacher-02").status_code == 422


def test_four_five_distinct_students_and_no_individual_payload(overview: Overview) -> None:
    for index in range(1, 5):
        overview.evidence(index, f"student-{index:02d}")
    summary = overview.summary()
    assert summary.performance_state == "hidden" and summary.hidden is True
    assert summary.confirmed_evidence_count is summary.observed_student_count is None
    overview.evidence(5, "student-05")
    overview.evidence(6, "student-01")
    summary = overview.summary()
    assert summary.performance_state == "available" and summary.hidden is False
    assert summary.confirmed_evidence_count == 6
    assert summary.observed_student_count == 5
    serialized = summary.model_dump_json()
    for private in ("student-", "teacher-", QUOTE, "audio", "password"):
        assert private not in serialized


def test_other_teacher_cannot_change_authorized_totals(overview: Overview) -> None:
    classroom = overview.env.store.get_classroom("teacher-01", overview.env.cid)
    foreign = overview.env.store.create_classroom(
        "teacher-02",
        CreateClassroom.model_validate(
            classroom.model_dump(exclude={"id", "teacher_id", "revision"}) | {"idempotency_key": "foreign-classroom"}
        ),
    )
    for index in range(1, 6):
        overview.evidence(index, f"student-{index:02d}", foreign.id, "teacher-02")
    result = overview.summary()
    assert result.classroom_count == 1
    assert result.performance_state == "no_data"
    assert result.confirmed_evidence_count is result.observed_student_count is None


def test_adoption_retraction_and_immediate_invalid_basis(overview: Overview, control: ResponseInstaller) -> None:
    evidence = overview.evidence(1, "student-01")
    control(lambda request: support_output())
    client = overview.env.client
    prefix = f"/api/classrooms/{overview.env.cid}"
    body = {"evidence_id": evidence.id, "expected_evidence_revision": 2, "idempotency_key": "summary-support"}
    response = client.post(f"{prefix}/plans/generate", json=body)
    plan = PlanGenerationResult.model_validate_json(response.content).plan
    assert plan is not None
    content = plan.content.model_copy(
        update={"preparation": "比较面积", "alternative": "再举例", "keep_content": "平均分"}
    )
    response = client.put(
        f"{prefix}/plans/{plan.id}/review",
        json={
            "expected_revision": 1,
            "action": "confirmed",
            "content": content.model_dump(),
        },
    )
    plan = PlanRecord.model_validate_json(response.content)
    response = client.put(
        f"{prefix}/plans/{plan.id}/adoption",
        json={
            "expected_revision": plan.revision,
            "adopted": True,
            "observation": "已进行新题检查",
        },
    )
    plan = PlanRecord.model_validate_json(response.content)
    response = client.post(f"{prefix}/exercises/generate", json=body)
    exercise = ExerciseGenerationResult.model_validate_json(response.content).exercise_set
    assert exercise is not None
    response = client.put(
        f"{prefix}/exercises/{exercise.id}/review",
        json={
            "expected_revision": 1,
            "action": "confirmed",
        },
    )
    exercise = ExerciseRecord.model_validate_json(response.content)
    client.put(f"{prefix}/exercises/{exercise.id}/adoption", json={"expected_revision": 2, "adopted": True})
    summary = overview.summary()
    assert summary.adopted_plan_count == summary.adopted_exercise_count == summary.observation_count == 1
    assert [item.count for item in summary.resource_needs] == [1, 1, 0]
    assert summary.plan_metrics.generated_count == summary.plan_metrics.confirmed_count == 1
    assert summary.plan_metrics.adoption_rate.ratio == 1
    overview.login("teacher-01")
    client.put(f"{prefix}/plans/{plan.id}/adoption", json={"expected_revision": 3, "adopted": False})
    summary = overview.summary()
    assert summary.adopted_plan_count == summary.observation_count == 0
    assert summary.adopted_exercise_count == 1
    assert summary.plan_metrics.generated_count == summary.plan_metrics.confirmed_count == 1
    assert summary.plan_metrics.adoption_rate.denominator == 1
    assert summary.plan_metrics.adoption_rate.ratio == 0
    overview.login("teacher-01")
    overview.env.speech.review(
        overview.env.cid,
        "s-admin",
        "u-admin-1",
        "teacher-01",
        ReviewRequest(
            expected_version=2,
            student_alias="student-02",
            question_id="q-1",
            text_review="confirmed",
            identity_review="confirmed",
            question_review="confirmed",
        ),
    )
    summary = overview.summary()
    assert summary.adopted_plan_count == summary.adopted_exercise_count == summary.observation_count == 0
    assert summary.performance_state == "no_data"
    assert [item.count for item in summary.resource_needs] == [0, 0, 0]
    assert summary.plan_metrics.generated_count == summary.exercise_metrics.generated_count == 0
    assert summary.plan_metrics.adoption_rate.ratio is None
