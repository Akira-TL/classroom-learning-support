from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from ...audio.media import AudioAsset
from ...models import StrictModel
from ..models import CompareRequest

TagLabel = Literal[
    "cough", "pen_sound", "snoring", "sneeze", "chair_movement", "door_close", "desk_tap", "pen_drop",
    "inattention", "sleeping", "other",
]


class TagValue(StrictModel):
    tag_id: str = Field(min_length=1, max_length=100)
    label: TagLabel
    original_label: str = Field(min_length=1, max_length=100)
    category: Literal["audible_event", "external_state"]
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    count: int = Field(ge=0, le=10000)
    note: str = Field(default="", max_length=2000)
    original_value: float | str | None = None


    @model_validator(mode="after")
    def coherence(self) -> Self:
        if self.end_ms <= self.start_ms:
            raise ValueError("标签时间段无效")
        expected = "external_state" if self.label in {"inattention", "sleeping"} else "audible_event"
        if self.label != "other" and self.category != expected:
            raise ValueError("咳嗽等声音观测与走神等外部状态标签须分别标记")
        return self


class TimedTranscript(StrictModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=6000)

    @model_validator(mode="after")
    def times(self) -> Self:
        if self.end_ms <= self.start_ms:
            raise ValueError("转写时间段无效")
        return self


class TagImport(StrictModel):
    import_id: str = Field(min_length=1, max_length=100)
    student_id: str = Field(pattern=r"^student-[0-9]{2,4}$")
    observed_on: date
    session_id: str = Field(min_length=1, max_length=100)
    source_name: str = Field(min_length=1, max_length=300)
    source_version: str = Field(min_length=1, max_length=100)
    source_description: str = Field(min_length=1, max_length=2000)
    data_origin: Literal["provided_annotation", "demonstration"]
    capture_conditions: str = Field(min_length=1, max_length=1000)
    captured_duration_ms: int | None = Field(default=None, gt=0, le=86400000)
    identity_confirmed: bool = False
    confirmed: bool = False
    tags: list[TagValue] = Field(min_length=1, max_length=500)
    transcripts: list[TimedTranscript] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({tag.tag_id for tag in self.tags}) != len(self.tags):
            raise ValueError("同次导入标签标识不能重复")
        if self.captured_duration_ms is not None and (
            any(tag.end_ms > self.captured_duration_ms for tag in self.tags)
            or any(item.end_ms > self.captured_duration_ms for item in self.transcripts)
        ):
            raise ValueError("标签或转写时间超出采集时长，请核对采集范围和时间基准")
        return self


class TagUpdate(TagImport):
    expected_revision: int = Field(ge=1)


class TagBatch(TagImport):
    id: str
    classroom_id: str
    teacher_id: str
    revision: int = 1
    audio_asset: AudioAsset | None = None


class TagSummary(StrictModel):
    label: TagLabel
    baseline_count: int | None
    current_count: int | None
    count_difference: int | None
    baseline_duration_ms: int | None
    current_duration_ms: int | None
    baseline_per_hour: float | None
    current_per_hour: float | None
    rate_difference: float | None
    notes: list[str]


class TagComparison(StrictModel):
    periods: CompareRequest
    baseline: list[TagBatch]
    current: list[TagBatch]
    summaries: list[TagSummary]
    notes: list[str]


class TagBasis(StrictModel):
    batch_id: str
    revision: int = Field(ge=1)


class ExplainRequest(StrictModel):
    comparison: CompareRequest
    basis: list[TagBasis] = Field(min_length=1, max_length=100)


class Explanation(StrictModel):
    change_explanation: str = Field(min_length=1, max_length=5000)
    followup_questions: list[str] = Field(min_length=1, max_length=10)
    teacher_text: str = Field(min_length=1, max_length=5000)
    student_text: str = Field(min_length=1, max_length=5000)
    parent_text: str = Field(min_length=1, max_length=5000)
    followup: str = Field(min_length=1, max_length=3000)
