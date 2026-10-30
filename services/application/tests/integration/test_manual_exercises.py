import pytest
from test_evidence import PASSWORD, Environment
from test_evidence import environment as environment

from teaching.deletion.models import DeleteClassroom
from teaching.deletion.store import DeletionStore
from teaching.manual_exercises.models import CreateManualExercises, ManualExerciseRecord
from teaching.models import Exercise


@pytest.fixture
def manual(environment: Environment) -> Environment:
    return environment


def draft(key: str = "manual-create-01") -> CreateManualExercises:
    return CreateManualExercises(
        exercises=[
            Exercise(
                level="concept", question="整体平均分成4份，每份是多少？", answer="四分之一", explanation="四份相等"
            ),
            Exercise(
                level="explanation",
                question="为什么分成4块未必每块都是四分之一？",
                answer="还需每块相等",
                explanation="四分之一要求平均分成四份",
            ),
            Exercise(
                level="transfer",
                question="12个苹果平均分给4人，每人占总数多少？",
                answer="四分之一，即3个",
                explanation="每人得到相同的3个，占12个的四分之一",
            ),
        ],
        idempotency_key=key,
    )


def url(env: Environment) -> str:
    return f"/api/classrooms/{env.cid}/manual-exercises"


def test_general_origin_idempotency_and_request_conflict(manual: Environment) -> None:
    response = manual.client.post(url(manual), content=draft().model_dump_json())
    assert response.status_code == 200
    record = ManualExerciseRecord.model_validate_json(response.content)
    assert record.origin == "teacher_manual_general"
    assert record.status == "pending" and record.adopted is False
    assert record.created_by == "teacher-01"
    assert record.initial_exercises == record.exercises
    assert (
        ManualExerciseRecord.model_validate_json(
            manual.client.post(url(manual), content=draft().model_dump_json()).content
        ).id
        == record.id
    )
    edited = draft().model_copy(
        update={
            "exercises": [
                draft().exercises[0].model_copy(update={"answer": "1/4"}),
                *draft().exercises[1:],
            ]
        }
    )
    assert manual.client.post(url(manual), content=edited.model_dump_json()).status_code == 409
    assert manual.client.post(url(manual), json=draft().model_dump() | {"student_id": "student-01"}).status_code == 422
    serialized = record.model_dump_json()
    assert "evidence_id" not in serialized and "model" not in serialized and "student_id" not in serialized


def test_edit_confirmation_adoption_and_old_versions_preserve_content(manual: Environment) -> None:
    record = ManualExerciseRecord.model_validate_json(
        manual.client.post(url(manual), content=draft().model_dump_json()).content
    )
    endpoint = f"{url(manual)}/{record.id}"
    assert manual.client.put(f"{endpoint}/adoption", json={"expected_revision": 1, "adopted": True}).status_code == 409
    edited = [item.model_copy(update={"answer": f"教师核对：{item.answer}"}) for item in record.exercises]
    response = manual.client.put(
        f"{endpoint}/review",
        json={
            "expected_revision": 1,
            "action": "confirmed",
            "exercises": [item.model_dump() for item in edited],
        },
    )
    confirmed = ManualExerciseRecord.model_validate_json(response.content)
    assert confirmed.status == "confirmed" and confirmed.revision == 2 and confirmed.adopted is False
    assert confirmed.initial_exercises[0].answer == "四分之一"
    assert confirmed.exercises[0].answer == "教师核对：四分之一"
    assert (
        manual.client.put(f"{endpoint}/review", json={"expected_revision": 1, "action": "rejected"}).status_code == 409
    )
    response = manual.client.put(f"{endpoint}/adoption", json={"expected_revision": 2, "adopted": True})
    adopted = ManualExerciseRecord.model_validate_json(response.content)
    assert adopted.adopted and adopted.adopted_by == "teacher-01" and adopted.revision == 3
    response = manual.client.put(f"{endpoint}/adoption", json={"expected_revision": 3, "adopted": False})
    assert ManualExerciseRecord.model_validate_json(response.content).adopted is False
    response = manual.client.put(f"{endpoint}/review", json={"expected_revision": 4, "action": "rejected"})
    rejected = ManualExerciseRecord.model_validate_json(response.content)
    assert rejected.status == "rejected" and rejected.exercises == edited
    assert manual.client.put(f"{endpoint}/adoption", json={"expected_revision": 5, "adopted": True}).status_code == 409


def test_roles_and_personal_publication_cannot_bypass_evidence(manual: Environment) -> None:
    record = ManualExerciseRecord.model_validate_json(
        manual.client.post(url(manual), content=draft().model_dump_json()).content
    )
    response = manual.client.post(
        f"/api/classrooms/{manual.cid}/student-reports",
        json={
            "exercise_set_id": record.id,
            "expected_exercise_revision": 1,
            "student_id": "student-01",
            "feedback": "不应发布没有个体证据的通用练习",
            "idempotency_key": "manual-publish-no",
        },
    )
    assert response.status_code in {404, 409}
    for username in ("teacher-02", "student-01", "parent-01", "admin-01"):
        assert (
            manual.client.post("/api/auth/login", json={"username": username, "password": PASSWORD}).status_code == 200
        )
        assert manual.client.get(url(manual)).status_code == 403
        assert manual.client.post(url(manual), content=draft().model_dump_json()).status_code == 403
        assert (
            manual.client.put(
                f"{url(manual)}/{record.id}/review",
                json={
                    "expected_revision": 1,
                    "action": "confirmed",
                },
            ).status_code
            == 403
        )


def test_incomplete_layers_rejected_and_deleted_classroom_cannot_resurrect(manual: Environment) -> None:
    invalid = draft().model_dump()
    invalid["exercises"] = [draft().exercises[0].model_dump()] * 3
    assert manual.client.post(url(manual), json=invalid).status_code == 422
    record = ManualExerciseRecord.model_validate_json(
        manual.client.post(url(manual), content=draft().model_dump_json()).content
    )
    classroom = manual.store.get_classroom("teacher-01", manual.cid)
    DeletionStore(manual.store).create(
        manual.cid,
        "teacher-01",
        DeleteClassroom(
            expected_revision=classroom.revision,
            confirmation=classroom.title,
            idempotency_key="delete-manual-classroom",
        ),
    )
    assert manual.client.get(url(manual)).status_code == 404
    assert manual.client.post(url(manual), content=draft("manual-after-delete").model_dump_json()).status_code == 404
    assert (
        manual.client.put(
            f"{url(manual)}/{record.id}/adoption",
            json={
                "expected_revision": 1,
                "adopted": False,
            },
        ).status_code
        == 404
    )
