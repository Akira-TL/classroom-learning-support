from pydantic import TypeAdapter
from test_evidence import environment as environment
from test_evidence import model_response as model_response
from test_exercises import ExerciseEnvironment, ResponseInstaller, output
from test_exercises import control as control
from test_exercises import ready as ready

from teaching.classroom.storage import SQLiteStore
from teaching.exercises.models import ExerciseGenerationResult, ExerciseRecord
from teaching.exercises.store import ExerciseStore
from teaching.students.models import ReportSummary, ReportView


def test_pending_draft_persists_edits_with_original_and_optimistic_lock(
    ready: ExerciseEnvironment,
    control: ResponseInstaller,
) -> None:
    control(lambda request: output())
    record = ExerciseGenerationResult.model_validate_json(ready.generate().content).exercise_set
    changed = [item.model_copy(update={"answer": "1/4（四分之一）"}) for item in record.exercises]
    request = {"expected_revision": 1, "action": "pending", "exercises": [item.model_dump() for item in changed]}
    response = ready.env.client.put(f"{ready.url}/{record.id}/review", json=request)
    assert response.status_code == 200
    updated = ExerciseRecord.model_validate_json(response.content)
    assert updated.status == "pending" and updated.revision == 2 and not updated.adopted
    assert updated.exercises[0].answer == "1/4（四分之一）"
    assert updated.original.content.exercises[0].answer == "四分之一"
    reopened = ExerciseStore(SQLiteStore(ready.env.store.path)).list(ready.env.cid, "teacher-01")
    assert reopened[0].exercise_set == updated
    assert ready.env.client.put(f"{ready.url}/{record.id}/review", json=request).status_code == 409
    assert (
        ready.env.client.put(
            f"{ready.url}/{record.id}/adoption",
            json={
                "expected_revision": 2,
                "adopted": True,
            },
        ).status_code
        == 409
    )
    assert (
        ready.env.client.post(
            f"/api/classrooms/{ready.env.cid}/student-reports",
            json={
                "exercise_set_id": record.id,
                "expected_exercise_revision": 2,
                "student_id": "student-01",
                "feedback": "尚未核验不能发布",
                "idempotency_key": "pending-publish-01",
            },
        ).status_code
        == 409
    )


def test_saving_adopted_exercises_as_pending_invalidates_student_report(
    ready: ExerciseEnvironment,
    control: ResponseInstaller,
) -> None:
    control(lambda request: output())
    record = ExerciseGenerationResult.model_validate_json(ready.generate().content).exercise_set
    client = ready.env.client
    endpoint = f"{ready.url}/{record.id}"
    assert client.put(f"{endpoint}/review", json={"expected_revision": 1, "action": "confirmed"}).status_code == 200
    adopted = ExerciseRecord.model_validate_json(
        client.put(
            f"{endpoint}/adoption",
            json={"expected_revision": 2, "adopted": True},
        ).content
    )
    report = ReportView.model_validate_json(
        client.post(
            f"/api/classrooms/{ready.env.cid}/student-reports",
            json={
                "exercise_set_id": record.id,
                "expected_exercise_revision": adopted.revision,
                "student_id": "student-01",
                "feedback": "教师已核验的内容",
                "idempotency_key": "adopted-publish-01",
            },
        ).content
    )
    changed = [item.model_copy(update={"explanation": "教师重新编辑，尚未逐题复核"}) for item in record.exercises]
    saved = ExerciseRecord.model_validate_json(
        client.put(
            f"{endpoint}/review",
            json={
                "expected_revision": adopted.revision,
                "action": "pending",
                "exercises": [item.model_dump() for item in changed],
            },
        ).content
    )
    assert saved.status == "pending" and not saved.adopted and saved.adopted_by is None
    assert saved.original.content.exercises[0].explanation == "四份相等"
    client.post("/api/auth/login", json={"username": "student-01", "password": "evidence-test-password"})
    response = client.get(f"/api/student-reports/{report.id}")
    assert response.status_code == 410
    assert "教师已核验的内容" not in response.text
    summaries = TypeAdapter(list[ReportSummary]).validate_json(client.get("/api/student-reports").content)
    assert summaries[0].status == "stale"
