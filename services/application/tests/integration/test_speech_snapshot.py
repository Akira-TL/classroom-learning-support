from typing import TypedDict

import pytest
from test_evidence import Environment
from test_evidence import environment as environment

from teaching.audio.models import ReviewRequest, SpeechEvent, Utterance
from teaching.audio.store import SpeechConflict
from teaching.learning.models import GenerationResult, ManualEvidenceRequest
from teaching.models import EvidenceContent


class SnapshotChange(TypedDict, total=False):
    start_ms: int
    end_ms: int
    source_ref: str | None
    overlap: bool
    source_kind: str


def snapshot() -> SpeechEvent:
    return SpeechEvent(
        session_id="snapshot-session",
        event_id="initial",
        sequence=0,
        event_type="final",
        source_kind="synthetic",
        segment_id="snapshot-segment",
        revision=1,
        start_ms=100,
        end_ms=800,
        text="要平均分成四份",
        source_ref="left",
    )


def reviewed(env: Environment) -> Utterance:
    env.speech.receive(env.cid, snapshot())
    return env.speech.review(
        env.cid,
        "snapshot-session",
        "snapshot-segment",
        "teacher-01",
        ReviewRequest(
            expected_version=1,
            student_alias="student-01",
            question_id="q-1",
            teacher_text="教师保留的文本",
            text_review="confirmed",
            identity_review="confirmed",
            question_review="confirmed",
        ),
    )


@pytest.mark.parametrize(
    "change",
    [
        SnapshotChange(start_ms=101),
        SnapshotChange(end_ms=801),
        SnapshotChange(source_ref="right"),
        SnapshotChange(overlap=True),
        SnapshotChange(source_kind="recorded_result"),
    ],
)
def test_same_revision_changed_metadata_is_atomic_conflict(environment: Environment, change: SnapshotChange) -> None:
    before = reviewed(environment)
    events = environment.speech.events(environment.cid)
    altered = SpeechEvent.model_validate(snapshot().model_dump() | change | {"event_id": "new", "sequence": 1})
    response = environment.client.post(
        f"/api/classrooms/{environment.cid}/speech/events",
        content=altered.model_dump_json(),
    )
    assert response.status_code == 409
    current = next(
        item for item in environment.speech.timeline(environment.cid) if item.segment_id == "snapshot-segment"
    )
    assert current == before
    assert environment.speech.events(environment.cid) == events
    assert len(environment.speech.history(environment.cid, "snapshot-session", "snapshot-segment")) == 1


def test_same_snapshot_new_event_keeps_teacher_review(environment: Environment) -> None:
    before = reviewed(environment)
    manual = ManualEvidenceRequest(
        session_id="snapshot-session",
        segment_id="snapshot-segment",
        expected_version=2,
        idempotency_key="manual-snapshot-01",
        content=EvidenceContent(
            quote="教师保留的文本",
            interpretation="仅为本次回答的解释",
            limitation="只有一次回答",
            follow_up_question="为什么？",
        ),
    )
    response = environment.client.post(f"{environment.url}/manual", content=manual.model_dump_json())
    initial = GenerationResult.model_validate_json(response.content)
    assert initial.evidence.status == "pending"
    repeated = snapshot().model_copy(update={"event_id": "new-equivalent", "sequence": 9})
    assert environment.speech.receive(environment.cid, repeated) is True
    current = next(
        item for item in environment.speech.timeline(environment.cid) if item.segment_id == "snapshot-segment"
    )
    assert current == before
    assert current.version == 2
    assert current.text_review == current.identity_review == current.question_review == "confirmed"
    response = environment.client.post(f"{environment.url}/manual", content=manual.model_dump_json())
    retained = GenerationResult.model_validate_json(response.content)
    assert retained.evidence.status == "pending"
    assert retained.evidence.revision == initial.evidence.revision


def test_new_revision_metadata_changes_reset_confirmation(environment: Environment) -> None:
    reviewed(environment)
    changed = snapshot().model_copy(update={"event_id": "revision-2", "revision": 2, "source_ref": "right"})
    assert environment.speech.receive(environment.cid, changed) is True
    current = next(
        item for item in environment.speech.timeline(environment.cid) if item.segment_id == "snapshot-segment"
    )
    assert current.version == 3
    assert current.source_ref == "right"
    assert current.teacher_text == "教师保留的文本"
    assert current.text_review == current.identity_review == current.question_review == "pending"


def test_repeated_withdraw_without_text_uses_preserved_text(environment: Environment) -> None:
    reviewed(environment)
    withdrawn = snapshot().model_copy(
        update={
            "event_id": "withdraw-2",
            "event_type": "withdraw",
            "revision": 2,
            "text": None,
        }
    )
    assert environment.speech.receive(environment.cid, withdrawn) is True
    before = next(
        item for item in environment.speech.timeline(environment.cid) if item.segment_id == "snapshot-segment"
    )
    repeated = withdrawn.model_copy(update={"event_id": "withdraw-equivalent", "sequence": 5})
    assert environment.speech.receive(environment.cid, repeated) is True
    current = next(
        item for item in environment.speech.timeline(environment.cid) if item.segment_id == "snapshot-segment"
    )
    assert current == before
    assert current.upstream_text == snapshot().text
    changed = repeated.model_copy(update={"event_id": "withdraw-conflict", "overlap": True})
    with pytest.raises(SpeechConflict):
        environment.speech.receive(environment.cid, changed)


def test_partial_progress_and_same_revision_final_exception_remain(environment: Environment) -> None:
    partial = snapshot().model_copy(update={"event_type": "partial", "text": "要平均分"})
    environment.speech.receive(environment.cid, partial)
    progress = partial.model_copy(
        update={"event_id": "progress", "sequence": 1, "text": "要平均分成四份", "end_ms": 900}
    )
    environment.speech.receive(environment.cid, progress)
    final = snapshot().model_copy(update={"event_id": "final", "sequence": 2, "end_ms": 950})
    environment.speech.receive(environment.cid, final)
    current = next(
        item for item in environment.speech.timeline(environment.cid) if item.segment_id == "snapshot-segment"
    )
    assert current.phase == "final" and current.revision == 1 and current.version == 3
    assert current.end_ms == 950
    assert current.text_review == "pending"
