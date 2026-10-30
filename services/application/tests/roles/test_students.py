from dataclasses import dataclass

import pytest
from pydantic import TypeAdapter
from test_evidence import environment as environment
from test_evidence import model_response as model_response
from test_exercises import ExerciseEnvironment, ResponseInstaller, output
from test_exercises import control as control
from test_exercises import ready as ready

from teaching.exercises.models import ExerciseGenerationResult, ExerciseRecord
from teaching.students.models import FeedbackRecord, ReportPreview, ReportSummary, ReportView, StudentPublish


@dataclass
class Reports:
    ready: ExerciseEnvironment
    exercise: ExerciseRecord

    @property
    def url(self) -> str:
        return f"/api/classrooms/{self.ready.env.cid}/student-reports"

    def login(self, username: str) -> None:
        assert (
            self.ready.env.client.post(
                "/api/auth/login",
                json={
                    "username": username,
                    "password": "evidence-test-password",
                },
            ).status_code
            == 200
        )

    def confirm(self) -> None:
        edited = [item.model_copy(update={"answer": "1/4（四分之一）"}) for item in self.exercise.exercises]
        response = self.ready.env.client.put(
            f"{self.ready.url}/{self.exercise.id}/review",
            json={
                "expected_revision": 1,
                "action": "confirmed",
                "exercises": [item.model_dump() for item in edited],
            },
        )
        self.exercise = ExerciseRecord.model_validate_json(response.content)

    def request(self) -> StudentPublish:
        return StudentPublish(
            exercise_set_id=self.exercise.id,
            expected_exercise_revision=self.exercise.revision,
            student_id="student-01",
            feedback="请解释为何必须平均分",
            idempotency_key="publish-01",
        )

    def publish(self) -> ReportView:
        response = self.ready.env.client.post(self.url, content=self.request().model_dump_json())
        assert response.status_code == 200
        return ReportView.model_validate_json(response.content)


@pytest.fixture
def reports(ready: ExerciseEnvironment, control: ResponseInstaller) -> Reports:
    control(lambda request: output())
    exercise = ExerciseGenerationResult.model_validate_json(ready.generate().content).exercise_set
    return Reports(ready, exercise)


def test_preview_publish_teacher_snapshot_and_idempotency(reports: Reports) -> None:
    reports.confirm()
    client = reports.ready.env.client
    preview = client.post(
        f"{reports.url}/preview", content=reports.request().model_dump_json(exclude={"idempotency_key"})
    )
    assert ReportPreview.model_validate_json(preview.content).exercises[0].answer == "1/4（四分之一）"
    first = reports.publish()
    assert reports.publish().id == first.id
    changed = reports.request().model_copy(update={"feedback": "另一份内容"})
    assert client.post(reports.url, content=changed.model_dump_json()).status_code == 409
    reports.login("student-01")
    body = client.get(f"/api/student-reports/{first.id}")
    assert ReportView.model_validate_json(body.content).feedback == "请解释为何必须平均分"
    assert "original" not in body.text
    assert "evidence" not in body.text
    assert "audio" not in body.text
    summaries = client.get("/api/student-reports")
    assert len(TypeAdapter(list[ReportSummary]).validate_json(summaries.content)) == 1
    assert "feedback" not in summaries.text


def test_student_and_role_isolation(reports: Reports) -> None:
    reports.confirm()
    report = reports.publish()
    client = reports.ready.env.client
    for username in ("student-02", "teacher-02", "parent-01", "admin-01"):
        reports.login(username)
        assert client.get(f"/api/student-reports/{report.id}").status_code == 403
        assert (
            client.post(
                f"/api/student-reports/{report.id}/feedback",
                json={
                    "kind": "correction",
                    "text": "不是我的回答",
                    "idempotency_key": "feedback-01",
                },
            ).status_code
            == 403
        )
    reports.login("student-02")
    assert TypeAdapter(list[ReportSummary]).validate_json(client.get("/api/student-reports").content) == []
    reports.login("teacher-02")
    assert client.get(reports.url).status_code == 403


def test_unconfirmed_wrong_student_and_preview_version_race(reports: Reports) -> None:
    client = reports.ready.env.client
    assert client.post(reports.url, content=reports.request().model_dump_json()).status_code == 409
    reports.confirm()
    request = reports.request()
    wrong = request.model_copy(update={"student_id": "student-02"})
    assert client.post(reports.url, content=wrong.model_dump_json()).status_code == 422
    assert (
        client.post(f"{reports.url}/preview", content=request.model_dump_json(exclude={"idempotency_key"})).status_code
        == 200
    )
    client.put(f"{reports.ready.url}/{reports.exercise.id}/review", json={"expected_revision": 2, "action": "rejected"})
    assert client.post(reports.url, content=request.model_dump_json()).status_code == 409


def test_invalidated_report_reveals_only_metadata(reports: Reports) -> None:
    reports.confirm()
    report = reports.publish()
    reports.ready.env.verify(2, "student-02")
    reports.login("student-01")
    client = reports.ready.env.client
    response = client.get(f"/api/student-reports/{report.id}")
    assert response.status_code == 410
    assert "请解释为何必须平均分" not in response.text
    summaries = client.get("/api/student-reports")
    assert TypeAdapter(list[ReportSummary]).validate_json(summaries.content)[0].status == "stale"
    assert "exercises" not in summaries.text
    assert (
        client.post(
            f"/api/student-reports/{report.id}/feedback",
            json={
                "kind": "correction",
                "text": "旧报告",
                "idempotency_key": "feedback-new",
            },
        ).status_code
        == 410
    )


def test_feedback_queue_and_revoke_preserve_prior_feedback(reports: Reports) -> None:
    reports.confirm()
    report = reports.publish()
    client = reports.ready.env.client
    reports.login("student-01")
    payload = {"kind": "correction", "text": "想请老师核对我的发言", "idempotency_key": "feedback-01"}
    first = FeedbackRecord.model_validate_json(
        client.post(f"/api/student-reports/{report.id}/feedback", json=payload).content
    )
    duplicate = FeedbackRecord.model_validate_json(
        client.post(f"/api/student-reports/{report.id}/feedback", json=payload).content
    )
    assert first.id == duplicate.id
    assert first.report_revision == 1
    reports.login("teacher-01")
    queue_url = f"/api/classrooms/{reports.ready.env.cid}/student-feedback"
    queue = TypeAdapter(list[FeedbackRecord]).validate_json(client.get(queue_url).content)
    assert [item.id for item in queue] == [first.id]
    response = client.put(
        f"{queue_url}/{first.id}",
        json={
            "expected_revision": 1,
            "status": "accepted",
            "response": "已收到，将核对原始发言",
        },
    )
    assert FeedbackRecord.model_validate_json(response.content).report_revision == 1
    assert FeedbackRecord.model_validate_json(response.content).handled_by == "teacher-01"
    assert client.post(f"{reports.url}/{report.id}/revoke", json={"expected_revision": 1}).status_code == 200
    reports.login("student-01")
    assert client.get(f"/api/student-reports/{report.id}").status_code == 410
    history = TypeAdapter(list[FeedbackRecord]).validate_json(
        client.get(f"/api/student-reports/{report.id}/feedback").content
    )
    assert history[0].status == "accepted"
    assert (
        client.post(
            f"/api/student-reports/{report.id}/feedback", json=payload | {"idempotency_key": "feedback-new"}
        ).status_code
        == 410
    )
