from pathlib import Path

import pytest
from pydantic import ValidationError

from teaching.audio.models import ReviewRequest, SpeechEvent
from teaching.audio.store import SpeechConflict, SpeechStore


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


def test_duplicate_conflict_and_old_revision(tmp_path: Path) -> None:
    store = SpeechStore(tmp_path / "app.db")
    assert store.receive("c1", event()) is True
    assert store.receive("c1", event()) is False
    with pytest.raises(SpeechConflict):
        store.receive("c1", event(text="冲突内容"))
    store.receive("c1", event("e3", 3, "我改口了"))
    store.receive("c1", event("e2", 2, "旧文字"))
    assert store.timeline("c1")[0].upstream_text == "我改口了"
    assert len(store.events("c1")) == 3
    assert store.timeline("c1")[0].student_alias is None


def test_partial_to_final_is_not_teacher_confirmation(tmp_path: Path) -> None:
    store = SpeechStore(tmp_path / "app.db")
    partial = event().model_copy(update={"event_type": "partial"})
    store.receive("c1", partial)
    with pytest.raises(SpeechConflict):
        store.review("c1", "s1", "u1", "teacher-01", review())
    store.receive("c1", event("e2"))
    current = store.timeline("c1")[0]
    assert current.phase == "final"
    assert current.text_review == current.identity_review == "pending"
    assert current.version == 2


def test_teacher_edits_preserved_and_stale_review_rejected(tmp_path: Path) -> None:
    path = tmp_path / "app.db"
    store = SpeechStore(path)
    store.receive("c1", event())
    verified = store.review("c1", "s1", "u1", "teacher-01", review())
    assert verified.version == 2
    store.receive("c1", event("e2", 2, "上游修订"))
    current = SpeechStore(path).timeline("c1")[0]
    assert current.teacher_text == "四块就是四分之一"
    assert current.text_review == current.identity_review == current.question_review == "pending"
    assert current.version == 3
    assert current.source_kind == "synthetic"
    assert current.audio_available is False
    assert store.history("c1", "s1", "u1")[0].actor == "teacher-01"
    with pytest.raises(SpeechConflict):
        store.review("c1", "s1", "u1", "teacher-01", review(2))


def test_identity_change_increments_effective_version(tmp_path: Path) -> None:
    store = SpeechStore(tmp_path / "app.db")
    store.receive("c1", event())
    store.review("c1", "s1", "u1", "teacher-01", review())
    changed = review(2).model_copy(update={"student_alias": "student-02"})
    result = store.review("c1", "s1", "u1", "teacher-01", changed)
    assert result.version == 3
    assert result.revision == 1
    assert result.student_alias == "student-02"
    assert len(store.history("c1", "s1", "u1")) == 2


def test_ended_session_allows_duplicates_but_rejects_new_events(tmp_path: Path) -> None:
    store = SpeechStore(tmp_path / "app.db")
    store.receive("c1", event())
    store.receive(
        "c1", SpeechEvent(session_id="s1", event_id="end", sequence=2, event_type="end", source_kind="synthetic")
    )
    assert store.receive("c1", event()) is False
    with pytest.raises(SpeechConflict):
        store.receive("c1", event("late", 2))


def test_invalid_time_and_missing_identity_fail() -> None:
    with pytest.raises(ValidationError):
        SpeechEvent.model_validate(event().model_dump() | {"end_ms": 10})
    with pytest.raises(ValidationError):
        ReviewRequest.model_validate(review().model_dump() | {"student_alias": None})
