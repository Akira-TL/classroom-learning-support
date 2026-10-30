import httpx
import pytest
from integration.correction_fixtures import Environment
from integration.correction_fixtures import env as env

import teaching.audio.store as audio_store
from teaching.audio.models import ReviewRequest, SpeechEvent
from teaching.corrections.models import CorrectionApply, CorrectionAssessment, CorrectionResult
from teaching.corrections.store import CorrectionStore
from teaching.deepseek import ChatReply, Choice, DeepSeek, ReplyMessage
from teaching.exercises.models import ExerciseGenerationResult, ExerciseRecord
from teaching.learning.models import EvidenceRecord
from teaching.plans.models import PlanRecord

PASSWORD = "correction-test-password"


def test_correction_during_model_generation_cannot_restore_old_content(
    env: Environment,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = env.chain("u-1", "student-01")
    corrections = CorrectionStore(env.store, env.speech)

    def transport(_request: httpx.Request) -> httpx.Response:
        corrections.apply(env.cid, "teacher-01", correction())
        reply = ChatReply(
            choices=[
                Choice(
                    message=ReplyMessage(content=chain.exercise.original.content.model_dump_json()),
                    finish_reason="stop",
                )
            ]
        )
        return httpx.Response(200, content=reply.model_dump_json())

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        monkeypatch.setattr(
            DeepSeek, "from_environment", classmethod(lambda cls, unused: DeepSeek(client, "test-secret"))
        )
        response = env.client.post(
            f"{env.base}/exercises/generate",
            json={
                "evidence_id": chain.evidence.id,
                "expected_evidence_revision": 2,
                "idempotency_key": "late-exercise-result",
            },
        )
    result = ExerciseGenerationResult.model_validate_json(response.content)
    assert result.task.status == "stale"
    assert result.exercise_set is None
    assert result.task.discarded_draft is not None
    assert env.speech.timeline(env.cid)[0].student_alias == "student-02"


def test_invalidation_failure_rolls_back_fact_and_reports(env: Environment, monkeypatch: pytest.MonkeyPatch) -> None:
    chain = env.chain("u-1", "student-01")
    corrections = CorrectionStore(env.store, env.speech)

    def fail(*_args: object) -> None:
        raise RuntimeError("模拟同事务失效失败")

    monkeypatch.setattr(audio_store, "invalidate", fail)
    with pytest.raises(RuntimeError, match="模拟同事务失效失败"):
        corrections.apply(env.cid, "teacher-01", correction())
    assert env.speech.timeline(env.cid)[0].version == 2
    assert env.speech.timeline(env.cid)[0].student_alias == "student-01"
    assert env.client.get(f"/api/parent-reports/{chain.parent.id}").status_code == 200


def correction() -> CorrectionApply:
    return CorrectionApply(
        session_id="s-1",
        segment_id="u-1",
        idempotency_key="correction-01",
        review=ReviewRequest(
            expected_version=2,
            teacher_text="教师修正的原话",
            student_alias="student-02",
            question_id="q-1",
            text_review="confirmed",
            identity_review="confirmed",
            question_review="confirmed",
        ),
    )


def test_atomic_chain_invalidation_and_unrelated_student_preserved(env: Environment) -> None:
    chain = env.chain("u-1", "student-01")
    untouched = env.chain("u-2", "student-02")
    original_events = env.speech.events(env.cid)
    response = env.client.post(
        f"{env.base}/corrections/preview", content=correction().model_dump_json(exclude={"idempotency_key"})
    )
    assessment = CorrectionAssessment.model_validate_json(response.content)
    assert assessment.impact.counts.model_dump() == {
        "evidence": 1,
        "exercises": 1,
        "plans": 1,
        "student_reports": 1,
        "parent_reports": 1,
    }
    assert env.speech.timeline(env.cid)[0].version == 2
    response = env.client.post(f"{env.base}/corrections", content=correction().model_dump_json())
    result = CorrectionResult.model_validate_json(response.content)
    assert result.utterance.student_alias == "student-02"
    assert result.utterance.version == 3
    assert env.speech.events(env.cid) == original_events
    with env.store.connection() as db:
        exercise = ExerciseRecord.model_validate_json(
            db.execute("SELECT body FROM exercise_sets WHERE id=?", (chain.exercise.id,)).fetchone()[0]
        )
        plan = PlanRecord.model_validate_json(
            db.execute("SELECT body FROM plan_records WHERE id=?", (chain.plan.id,)).fetchone()[0]
        )
        other = EvidenceRecord.model_validate_json(
            db.execute("SELECT body FROM evidence_records WHERE id=?", (untouched.evidence.id,)).fetchone()[0]
        )
    assert exercise.status == plan.status == "stale"
    assert not exercise.adopted and not plan.adopted
    assert exercise.exercises[0].answer == "教师保留的 1/4"
    assert plan.observations[0].text == "人工观察应保留"
    assert other.status == "confirmed"
    assert (
        env.client.post(f"{env.base}/corrections", content=correction().model_dump_json()).content == response.content
    )
    changed = correction().model_copy(update={"segment_id": "u-2"})
    assert env.client.post(f"{env.base}/corrections", content=changed.model_dump_json()).status_code == 409
    assert (
        env.client.post(
            f"{env.base}/parent-reports",
            json={
                "evidence_id": chain.evidence.id,
                "expected_evidence_revision": 2,
                "student_id": "student-01",
                "summary": "过期依据",
                "home_activity": "不应发布",
                "idempotency_key": "late-parent-publish",
            },
        ).status_code
        == 409
    )
    env.client.post("/api/auth/login", json={"username": "parent-01", "password": PASSWORD})
    assert env.client.get(f"/api/parent-reports/{chain.parent.id}").status_code == 410
    env.client.post("/api/auth/login", json={"username": "student-01", "password": PASSWORD})
    assert env.client.get(f"/api/student-reports/{chain.student.id}").status_code == 410


def test_direct_upstream_revision_also_invalidates_without_waiting_for_read(env: Environment) -> None:
    chain = env.chain("u-1", "student-01")
    env.speech.receive(
        env.cid,
        SpeechEvent(
            session_id="s-1",
            event_id="revision-02",
            sequence=2,
            segment_id="u-1",
            revision=2,
            event_type="revision",
            source_kind="synthetic",
            text="新的上游文字",
        ),
    )
    with env.store.connection() as db:
        record = EvidenceRecord.model_validate_json(
            db.execute(
                "SELECT body FROM evidence_records WHERE id=?",
                (chain.evidence.id,),
            ).fetchone()[0]
        )
    assert record.status == "stale"
    assert env.speech.timeline(env.cid)[0].text_review == "pending"


def test_stale_preview_and_cross_role_requests_rejected(env: Environment) -> None:
    env.chain("u-1", "student-01")
    changed = correction().model_copy(update={"review": correction().review.model_copy(update={"expected_version": 1})})
    assert env.client.post(f"{env.base}/corrections", content=changed.model_dump_json()).status_code == 409
    for username in ("teacher-02", "student-01", "parent-01", "admin-01"):
        env.client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
        assert env.client.post(f"{env.base}/corrections", content=correction().model_dump_json()).status_code == 403
