from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from teaching.audio.models import ReviewRequest, SpeechEvent
from teaching.audio.store import SpeechConflict, SpeechStore
from teaching.classroom.classrooms import CreateClassroom, Question
from teaching.classroom.storage import SQLiteStore, StoreError
from teaching.deletion.models import DeleteClassroom
from teaching.deletion.store import DeletionStore


@pytest.fixture
def classroom(tmp_path: Path) -> tuple[SpeechStore, str]:
    path = tmp_path / "app.db"
    created = SQLiteStore(path).create_classroom(
        "teacher-01",
        CreateClassroom(
            title="语音行为测试",
            date=date(2026, 10, 31),
            objective="理解平均分",
            students=["student-01", "student-02"],
            questions=[Question(id="q1", text="四块都是四分之一吗？", reference_answer="须平均分")],
            source="合成事件",
            authorization="仅供自动验证",
            idempotency_key="speech-fixture-classroom",
        ),
    )
    return SpeechStore(path), created.id


def event(event_id: str = "e1", revision: int = 1, text: str = "分成四块就是四分之一") -> SpeechEvent:
    return SpeechEvent(
        session_id="s1",
        event_id=event_id,
        sequence=revision,
        event_type="final",
        source_kind="synthetic",
        segment_id="u1",
        revision=revision,
        start_ms=100,
        end_ms=800,
        text=text,
        source_ref="direction-left",
    )


def review(version: int = 1) -> ReviewRequest:
    return ReviewRequest(
        expected_version=version,
        teacher_text="四块就是四分之一",
        student_alias="student-01",
        question_id="q1",
        text_review="confirmed",
        identity_review="confirmed",
        question_review="confirmed",
    )


def test_duplicate_conflict_and_old_revision(classroom: tuple[SpeechStore, str]) -> None:
    store, cid = classroom
    assert store.receive(cid, event()) is True
    assert store.receive(cid, event()) is False
    with pytest.raises(SpeechConflict):
        store.receive(cid, event(text="冲突内容"))
    store.receive(cid, event("e3", 3, "我改口了"))
    store.receive(cid, event("e2", 2, "旧文字"))
    assert store.timeline(cid)[0].upstream_text == "我改口了"
    assert len(store.events(cid)) == 3
    assert store.timeline(cid)[0].student_alias is None


def test_partial_to_final_is_not_teacher_confirmation(classroom: tuple[SpeechStore, str]) -> None:
    store, cid = classroom
    partial = event().model_copy(update={"event_type": "partial"})
    store.receive(cid, partial)
    with pytest.raises(SpeechConflict):
        store.review(cid, "s1", "u1", "teacher-01", review())
    store.receive(cid, event("e2"))
    current = store.timeline(cid)[0]
    assert current.phase == "final"
    assert current.text_review == current.identity_review == "pending"
    assert current.version == 2


def test_teacher_edits_preserved_and_stale_review_rejected(classroom: tuple[SpeechStore, str]) -> None:
    store, cid = classroom
    path = store.path
    store.receive(cid, event())
    verified = store.review(cid, "s1", "u1", "teacher-01", review())
    assert verified.version == 2
    store.receive(cid, event("e2", 2, "上游修订"))
    current = SpeechStore(path).timeline(cid)[0]
    assert current.teacher_text == "四块就是四分之一"
    assert current.text_review == current.identity_review == current.question_review == "pending"
    assert current.version == 3
    assert current.source_kind == "synthetic"
    assert current.audio_available is False
    assert store.history(cid, "s1", "u1")[0].actor == "teacher-01"
    with pytest.raises(SpeechConflict):
        store.review(cid, "s1", "u1", "teacher-01", review(2))


def test_identity_change_increments_effective_version(classroom: tuple[SpeechStore, str]) -> None:
    store, cid = classroom
    store.receive(cid, event())
    store.review(cid, "s1", "u1", "teacher-01", review())
    changed = review(2).model_copy(update={"student_alias": "student-02"})
    result = store.review(cid, "s1", "u1", "teacher-01", changed)
    assert result.version == 3
    assert result.revision == 1
    assert result.student_alias == "student-02"
    assert len(store.history(cid, "s1", "u1")) == 2


def test_ended_session_allows_duplicates_but_rejects_new_events(classroom: tuple[SpeechStore, str]) -> None:
    store, cid = classroom
    store.receive(cid, event())
    store.receive(
        cid, SpeechEvent(session_id="s1", event_id="end", sequence=2, event_type="end", source_kind="synthetic")
    )
    assert store.receive(cid, event()) is False
    with pytest.raises(SpeechConflict):
        store.receive(cid, event("late", 2))


def test_invalid_time_and_missing_identity_fail() -> None:
    with pytest.raises(ValidationError):
        SpeechEvent.model_validate(event().model_dump() | {"end_ms": 10})
    with pytest.raises(ValidationError):
        ReviewRequest.model_validate(review().model_dump() | {"student_alias": None})


def test_no_classroom_table_never_allows_writes(tmp_path: Path) -> None:
    speech = SpeechStore(tmp_path / "uninitialized.db")
    with pytest.raises(StoreError) as error:
        speech.receive("missing", event())
    assert error.value.status == 410
    with pytest.raises(StoreError) as error:
        speech.review("missing", "s1", "u1", "teacher-01", review())
    assert error.value.status == 410
    assert speech.events("missing") == []


def test_deleted_classroom_cannot_be_recreated_by_late_speech(classroom: tuple[SpeechStore, str]) -> None:
    speech, cid = classroom
    speech.receive(cid, event())
    classrooms = SQLiteStore(speech.path)
    # 授权检查成功之后发生删除，模拟接收请求在取得写事务前被延迟。
    current = classrooms.get_classroom("teacher-01", cid)
    DeletionStore(classrooms).create(
        cid,
        "teacher-01",
        DeleteClassroom(
            expected_revision=current.revision,
            confirmation=current.title,
            idempotency_key="speech-delete-race",
        ),
    )
    with pytest.raises(StoreError) as error:
        speech.receive(cid, event("late-event", 2))
    assert error.value.status == 410
    with pytest.raises(StoreError) as error:
        speech.review(cid, "s1", "u1", "teacher-01", review())
    assert error.value.status == 410
    assert speech.events(cid) == []
    assert speech.timeline(cid) == []
