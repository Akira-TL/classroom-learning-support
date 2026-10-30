from pathlib import Path

import pytest

from teaching.audio.models import SpeechEvent
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
    store.receive("c1", event("e2"))
    current = store.timeline("c1")[0]
    assert current.phase == "final"
    assert current.text_review == current.identity_review == "pending"
    assert current.version == 2


def test_ended_session_allows_duplicates_but_rejects_new_events(tmp_path: Path) -> None:
    store = SpeechStore(tmp_path / "app.db")
    store.receive("c1", event())
    store.receive(
        "c1", SpeechEvent(session_id="s1", event_id="end", sequence=2, event_type="end", source_kind="synthetic")
    )
    assert store.receive("c1", event()) is False
    with pytest.raises(SpeechConflict):
        store.receive("c1", event("late", 2))
