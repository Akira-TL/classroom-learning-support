from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from ..models import StrictModel


class AcousticMeasurements(StrictModel):
    reliability: Literal["verified"]
    method: str = Field(min_length=1, max_length=300)
    pitch_hz: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    level_dbfs: float | None = Field(default=None, le=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def has_measurement(self) -> Self:
        if self.pitch_hz is None and self.level_dbfs is None:
            raise ValueError("至少提供一项实际测量，缺失值不能作为测量结果")
        return self


class ObservationInput(StrictModel):
    session_id: str = Field(min_length=1, max_length=80)
    segment_id: str = Field(min_length=1, max_length=80)
    expected_utterance_version: int = Field(ge=1)
    student_id: str = Field(pattern=r"^student-[0-9]{2,4}$")
    observed_on: date
    fact: str = Field(min_length=1, max_length=3000)
    capture_conditions: str = Field(min_length=1, max_length=1000)
    teacher_note: str = Field(default="", max_length=3000)
    confirmed: bool = False


class ObservationUpdate(ObservationInput):
    expected_revision: int = Field(ge=1)


class Observation(ObservationInput):
    id: str
    classroom_id: str
    teacher_id: str
    revision: int = 1
    measurements: AcousticMeasurements | None = None
    measurement_note: str = "上游尚未提供可核查的可靠声学测量"
    source_current: bool = True


class CompareRequest(StrictModel):
    student_id: str = Field(pattern=r"^student-[0-9]{2,4}$")
    baseline_start: date
    baseline_end: date
    current_start: date
    current_end: date

    @model_validator(mode="after")
    def dates(self) -> Self:
        if not self.baseline_start <= self.baseline_end < self.current_start <= self.current_end:
            raise ValueError("两个时间段必须按先后排列且不重叠")
        return self


class MetricComparison(StrictModel):
    name: Literal["pitch_hz", "level_dbfs"]
    unit: Literal["Hz", "dBFS"]
    baseline_count: int
    current_count: int
    baseline_mean: float | None
    current_mean: float | None
    difference: float | None
    comparable: bool
    explanation: str


class Comparison(StrictModel):
    periods: CompareRequest
    baseline: list[Observation]
    current: list[Observation]
    metrics: list[MetricComparison]
    notes: list[str]


class Basis(StrictModel):
    observation_id: str
    revision: int = Field(ge=1)


class ReportInput(StrictModel):
    comparison: CompareRequest
    basis: list[Basis] = Field(min_length=1, max_length=100)
    teacher_text: str = Field(min_length=1, max_length=5000)
    student_text: str = Field(min_length=1, max_length=5000)
    parent_text: str = Field(min_length=1, max_length=5000)
    followup: str = Field(min_length=1, max_length=3000)


class CareReport(ReportInput):
    id: str
    classroom_id: str
    teacher_id: str
    student_id: str
    revision: int = 1
    status: Literal["draft", "published", "revoked", "stale"] = "draft"


class ReportAction(StrictModel):
    expected_revision: int = Field(ge=1)
    action: Literal["publish", "revoke"]
    teacher_confirmed: Literal[True]


class RecipientReport(StrictModel):
    id: str
    revision: int
    student_id: str
    audience: Literal["student", "parent"]
    text: str
    status: Literal["published"] = "published"
