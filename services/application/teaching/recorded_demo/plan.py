from datetime import date, timedelta

from ..audio.models import SpeechEvent
from ..care.tags.compare import LABELS
from ..care.tags.models import TagImport, TagLabel, TagValue, TimedTranscript
from .models import Recording, SoundEvent

STUDENTS = ("student-01", "student-02", "student-03")


def classify(event: SoundEvent) -> TagLabel | None:
    label = event.label
    mappings: tuple[tuple[str, TagLabel], ...] = (
        ("咳嗽", "cough"), ("按笔", "pen_sound"), ("呼噜", "snoring"), ("喷嚏", "sneeze"),
        ("板凳", "chair_movement"), ("关门", "door_close"), ("拍桌", "desk_tap"), ("摔笔", "pen_drop"),
    )
    for text, value in mappings:
        if text in label:
            return value
    if "老师声音" in label:
        return None
    raise ValueError(f"尚未映射的声音事件：{label}")


def student_for(label: TagLabel) -> str:
    if label in {"cough", "sneeze"}:
        return "student-02"
    if label in {"snoring", "desk_tap"}:
        return "student-03"
    return "student-01"


def speech_events(recording: Recording, session: str) -> list[SpeechEvent]:
    result = [SpeechEvent(session_id=session, event_id=f"line-{index:03d}", sequence=index,
                          event_type="final", source_kind="recorded_result", segment_id=f"line-{index:03d}",
                          start_ms=line.start_ms, end_ms=line.end_ms, text=line.text, source_ref=line.speaker)
              for index, line in enumerate(recording.transcripts)]
    result.append(SpeechEvent(session_id=session, event_id="end", sequence=len(result),
                              event_type="end", source_kind="recorded_result", status="ended"))
    return result


def mock_batches(recording: Recording, key: str, observed_on: date) -> list[TagImport]:
    results: list[TagImport] = []
    for student in STUDENTS:
        current: list[TagValue] = []
        for event in recording.events:
            label = classify(event)
            if label is not None and student_for(label) == student:
                current.append(TagValue(tag_id=event.id, label=label, original_label=event.label,
                                        category="audible_event", start_ms=event.start_ms,
                                        end_ms=event.end_ms if event.end_ms is not None else event.start_ms + 1,
                                        count=1))
        if student == "student-02":
            current.append(TagValue(tag_id="state-attention", label="inattention", original_label="走神",
                                    category="external_state", start_ms=46000, end_ms=48000, count=1))
        if student == "student-03":
            current.append(TagValue(tag_id="state-sleep", label="sleeping", original_label="睡觉",
                                    category="external_state", start_ms=54000, end_ms=57000, count=1))
        for label in LABELS:
            if not any(tag.label == label for tag in current):
                current.append(zero_tag(label))
        baseline = [zero_tag(label) for label in LABELS]
        baseline = [tag.model_copy(update={"count": 1, "start_ms": 10000, "end_ms": 11000})
                    if (student, tag.label) in {("student-02", "cough"), ("student-01", "pen_sound")} else tag
                    for tag in baseline]
        for period, day, tags in (("current", observed_on, current),
                                  ("baseline", observed_on - timedelta(days=7), baseline)):
            results.append(TagImport(
                import_id=f"{key}-{period}-{student}", student_id=student, observed_on=day,
                session_id=key if period == "current" else f"{key}-baseline",
                source_name=recording.title, source_version="1", source_description="演示数据",
                data_origin="demonstration", capture_conditions="课堂录制演示",
                captured_duration_ms=recording.duration_ms,
                identity_confirmed=False, confirmed=False, tags=sorted(tags, key=lambda item: item.start_ms),
                transcripts=[TimedTranscript(start_ms=line.start_ms, end_ms=line.end_ms, text=line.text)
                             for line in recording.transcripts
                             if period == "current" and line.speaker in {student, "teacher"}],
            ))
    return results


def zero_tag(label: TagLabel) -> TagValue:
    return TagValue(tag_id=f"zero-{label}", label=label, original_label=label,
                    category="external_state" if label in {"inattention", "sleeping"} else "audible_event",
                    start_ms=0, end_ms=1, count=0)
