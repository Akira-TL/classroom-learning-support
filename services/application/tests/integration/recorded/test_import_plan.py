from datetime import date

import pytest
from pydantic import ValidationError

from teaching.recorded_demo.models import Recording, SoundEvent, Transcript
from teaching.recorded_demo.plan import mock_batches, speech_events


def recording() -> Recording:
    return Recording(title="测试录制", audio_path="unused.wav", duration_ms=160385,
                     transcripts=[Transcript(start_ms=0, end_ms=4000, speaker="teacher", text="上课"),
                                  Transcript(start_ms=30000, end_ms=33000, speaker="student-02", text="2")],
                     events=[SoundEvent(id="addition-cough", part="addition", original_start_ms=13000,
                                        original_end_ms=14000, start_ms=11000, end_ms=12000,
                                        label="咳嗽", category="人声"),
                             SoundEvent(id="sub-point", part="subtraction", original_start_ms=50000,
                                        start_ms=136000, label="拍桌声", category="环境音")])


def test_recording_rejects_offset_error_and_out_of_range() -> None:
    source = recording()
    with pytest.raises(ValidationError, match="起点未按"):
        SoundEvent.model_validate(source.events[0].model_dump() | {"start_ms":13000})
    with pytest.raises(ValidationError, match="超出混音"):
        Recording.model_validate(source.model_dump() | {"duration_ms":100000})


def test_transcripts_keep_roles_text_and_recorded_origin() -> None:
    events = speech_events(recording(), "test-session")
    assert [(item.start_ms, item.end_ms, item.source_ref, item.text) for item in events[:-1]] == [
        (0, 4000, "teacher", "上课"), (30000, 33000, "student-02", "2"),
    ]
    assert all(item.source_kind == "recorded_result" and item.native_event is None for item in events)
    assert events[-1].event_type == "end" and events[-1].sequence == 2


def test_mock_history_is_stable_separate_and_has_explicit_zero() -> None:
    source = recording()
    first = mock_batches(source, "stable", date(2026, 10, 31))
    assert first == mock_batches(source, "stable", date(2026, 10, 31))
    assert len(first) == 6
    current = next(item for item in first if item.student_id == "student-02" and item.observed_on.day == 31)
    previous = next(item for item in first if item.student_id == "student-02" and item.observed_on.day == 24)
    assert current.session_id != previous.session_id
    assert current.data_origin == previous.data_origin == "demonstration"
    assert sum(tag.count for tag in current.tags if tag.label == "cough") == 1
    assert next(tag.count for tag in previous.tags if tag.label == "snoring") == 0
    point = next(tag for batch in first for tag in batch.tags if tag.tag_id == "sub-point")
    assert (point.start_ms, point.end_ms) == (136000, 136001)
    assert source.events[1].end_ms is None
