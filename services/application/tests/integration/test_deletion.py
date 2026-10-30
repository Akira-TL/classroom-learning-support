import io
import wave
from pathlib import Path

import httpx
import pytest
from roles.test_exports import Exports
from roles.test_exports import exports as exports
from test_evidence import environment as environment
from test_evidence import model_response as model_response
from test_exercises import ResponseInstaller, output
from test_exercises import control as control
from test_exercises import ready as ready
from test_plans import planning as planning

from teaching.audio.media import AudioStore
from teaching.classroom.classrooms import CreateClassroom
from teaching.classroom.storage import StoreError
from teaching.corrections.store import CorrectionStore
from teaching.deletion.models import DeleteClassroom, DeletionView, Resource
from teaching.deletion.resources import remove_resource
from teaching.deletion.store import DeletionStore
from teaching.exercises.models import ExerciseGenerationResult
from teaching.exports.models import ExportMetadata
from teaching.reports.models import PublishRequest
from teaching.reports.store import ReportStore
from teaching.students.feedback import Feedback
from teaching.students.models import HandleFeedback, ReportView, StudentFeedbackRequest
from teaching.students.store import StudentStore


def wav() -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\0\0" * 1600)
    return stream.getvalue()


def request(exports: Exports) -> DeleteClassroom:
    env = exports.planning.ready.env
    classroom = env.store.get_classroom("teacher-01", env.cid)
    return DeleteClassroom(
        expected_revision=classroom.revision, confirmation=classroom.title, idempotency_key="delete-classroom-01"
    )


def test_full_chain_cleanup_keeps_other_classroom(exports: Exports, control: ResponseInstaller) -> None:
    env = exports.planning.ready.env
    CorrectionStore(env.store, env.speech)
    exported = exports.create()
    audio = AudioStore(env.store.path)
    asset = audio.save(env.cid, "audio-session", wav())
    content = env.store.get_classroom("teacher-01", env.cid)
    other = env.store.create_classroom(
        "teacher-01",
        CreateClassroom(
            **content.model_dump(exclude={"id", "teacher_id", "revision"}),
            idempotency_key="other-classroom-01",
        ),
    )
    other_asset = audio.save(other.id, "audio-session", wav())
    control(lambda message: output())
    exercise = ExerciseGenerationResult.model_validate_json(exports.planning.ready.generate().content).exercise_set
    env.client.put(
        f"{exports.planning.ready.url}/{exercise.id}/review", json={"expected_revision": 1, "action": "confirmed"}
    )
    response = env.client.post(
        f"/api/classrooms/{env.cid}/student-reports",
        json={
            "exercise_set_id": exercise.id,
            "expected_exercise_revision": 2,
            "student_id": "student-01",
            "feedback": "待删除的个人反馈正文",
            "idempotency_key": "publish-delete-01",
        },
    )
    student = ReportView.model_validate_json(response.content)
    feedback = Feedback(StudentStore(env.store))
    item = feedback.submit(
        student.id,
        "student-01",
        StudentFeedbackRequest(
            kind="correction",
            text="待删除的反馈",
            idempotency_key="feedback-delete-01",
        ),
    )
    feedback.handle(
        env.cid,
        "teacher-01",
        item.id,
        HandleFeedback(
            expected_revision=1,
            status="accepted",
            response="待删除的处理意见",
        ),
    )
    parent = ReportStore(env.store).publish(
        env.cid,
        "teacher-01",
        PublishRequest(
            evidence_id=exports.plan.evidence_id,
            expected_evidence_revision=exports.plan.evidence_revision,
            student_id="student-01",
            summary="待删除的家长正文",
            home_activity="待删除活动",
            idempotency_key="parent-delete-01",
        ),
    )
    payload = request(exports)
    response = env.client.post(f"/api/classrooms/{env.cid}/deletion", content=payload.model_dump_json())
    task = DeletionView.model_validate_json(response.content)
    assert task.local_complete is True and task.external_pending is True
    assert task.external_status == "not_requested"
    assert not (audio.root / f"{asset.id}.wav").exists()
    assert (audio.root / f"{other_asset.id}.wav").is_file()
    assert not (env.store.path.parent / "exports" / f"{exported.id}.html").exists()
    assert env.store.get_classroom("teacher-01", other.id).id == other.id
    assert env.client.get(f"/api/classrooms/{env.cid}").status_code == 404
    assert env.client.get(f"/api/exports/{exported.id}/download").status_code == 410
    assert (
        ExportMetadata.model_validate_json(env.client.get(f"/api/exports/{exported.id}/status").content).status
        == "deleted"
    )
    again = env.client.post(f"/api/classrooms/{env.cid}/deletion", content=payload.model_dump_json())
    assert DeletionView.model_validate_json(again.content).id == task.id
    assert (
        env.client.post(
            f"/api/classrooms/{env.cid}/deletion",
            content=payload.model_copy(
                update={"idempotency_key": "another-delete-key"},
            ).model_dump_json(),
        ).status_code
        == 410
    )
    exports.login("student-01")
    assert env.client.get(f"/api/student-reports/{student.id}").status_code == 404
    exports.login("parent-01")
    assert env.client.get(f"/api/parent-reports/{parent.id}").status_code == 404
    with env.store.connection() as db:
        for table in (
            "evidence_tasks",
            "exercise_tasks",
            "plan_tasks",
            "speech_reviews",
            "student_feedback",
            "parent_reports",
            "teacher_exports",
            "corrections",
        ):
            assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE classroom_id=?", (env.cid,)).fetchone()[0] == 0
        body = db.execute("SELECT body FROM classroom_deletions WHERE id=?", (task.id,)).fetchone()[0]
    assert "待删除的个人反馈正文" not in body and "分成四块" not in body


def test_authorization_confirmation_and_version(exports: Exports) -> None:
    env = exports.planning.ready.env
    payload = request(exports)
    exports.login("teacher-02")
    assert env.client.post(f"/api/classrooms/{env.cid}/deletion", content=payload.model_dump_json()).status_code == 403
    exports.login("teacher-01")
    for changes, status in (({"confirmation": "wrong"}, 422), ({"expected_revision": 999}, 409)):
        assert (
            env.client.post(
                f"/api/classrooms/{env.cid}/deletion",
                content=payload.model_copy(
                    update=changes,
                ).model_dump_json(),
            ).status_code
            == status
        )
    task = DeletionView.model_validate_json(
        env.client.post(
            f"/api/classrooms/{env.cid}/deletion",
            content=payload.model_dump_json(),
        ).content
    )
    exports.login("teacher-02")
    assert env.client.get(f"/api/classroom-deletions/{task.id}").status_code == 403
    assert env.client.post(f"/api/classroom-deletions/{task.id}/retry").status_code == 403


def test_file_failure_retries_without_reopening_sources(exports: Exports, monkeypatch: pytest.MonkeyPatch) -> None:
    env = exports.planning.ready.env
    exported = exports.create()

    def fail(root: Path, resource: Resource) -> None:
        raise OSError("private filesystem details")

    with monkeypatch.context() as patch:
        patch.setattr("teaching.deletion.store.remove_resource", fail)
        result = DeletionView.model_validate_json(
            env.client.post(
                f"/api/classrooms/{env.cid}/deletion",
                content=request(exports).model_dump_json(),
            ).content
        )
    assert not result.local_complete and result.remaining_files == 1
    assert "private filesystem" not in result.model_dump_json()
    assert env.client.get(f"/api/exports/{exported.id}/download").status_code == 410
    retried = DeletionView.model_validate_json(env.client.post(f"/api/classroom-deletions/{result.id}/retry").content)
    assert retried.local_complete and retried.remaining_files == 0


@pytest.mark.parametrize("kind", ["evidence", "exercise", "plan"])
def test_late_generation_after_delete_returns_no_old_content(
    exports: Exports,
    control: ResponseInstaller,
    kind: str,
) -> None:
    env = exports.planning.ready.env
    store = DeletionStore(env.store)
    payload = request(exports)

    def response(message: httpx.Request) -> httpx.Response:
        store.create(env.cid, "teacher-01", payload)
        if kind == "evidence":
            from test_evidence import output as evidence_output

            return evidence_output()
        return output()

    control(response)
    if kind == "evidence":
        result = env.client.post(
            f"{env.url}/generate",
            json={
                "session_id": "s-1",
                "segment_id": "u-1",
                "expected_version": 2,
                "idempotency_key": "late-evidence-01",
            },
        )
    elif kind == "exercise":
        result = exports.planning.ready.generate("late-exercise-01")
    else:
        result = exports.planning.generate("late-plan-01")
    assert result.status_code == 410
    assert "分成四块" not in result.text and "interpretation" not in result.text


def test_audio_save_checks_after_parsing_and_path_escape_is_refused(
    exports: Exports,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = exports.planning.ready.env
    audio = AudioStore(env.store.path)
    payload = request(exports)
    store = DeletionStore(env.store)
    original = wave.open

    def parse(stream: io.BytesIO, mode: str) -> wave.Wave_read:
        result = original(stream, mode)
        store.create(env.cid, "teacher-01", payload)
        return result

    content = wav()
    with monkeypatch.context() as patch:
        patch.setattr("teaching.audio.media.wave.open", parse)
        with pytest.raises(StoreError, match="课堂已删除"):
            audio.save(env.cid, "late-audio", content)
    assert list(audio.root.iterdir()) == []
    with pytest.raises(OSError, match="资源标识"):
        remove_resource(env.store.path.parent, Resource(kind="export", id="../escape"))
