from datetime import datetime
from typing import Literal

from pydantic import Field

from ..models import StrictModel


class ResourceNeed(StrictModel):
    kind: Literal["exercise_materials", "teaching_activities", "manual_exercise_materials"]
    description: str
    count: int = Field(ge=0)


class CountRatio(StrictModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    ratio: float | None = Field(default=None, ge=0, le=1)


class SupportMetrics(StrictModel):
    source: Literal["model_generated"] = "model_generated"
    generated_count: int = Field(ge=0)
    confirmed_count: int = Field(ge=0)
    adopted_count: int = Field(ge=0)
    confirmation_rate: CountRatio
    adoption_rate: CountRatio


class ManualMetrics(StrictModel):
    source: Literal["teacher_manual_general"] = "teacher_manual_general"
    recorded_count: int = Field(ge=0)
    confirmed_count: int = Field(ge=0)
    adopted_count: int = Field(ge=0)
    confirmation_rate: CountRatio
    adoption_rate: CountRatio


class AdminSummary(StrictModel):
    scope: str
    snapshot_at: datetime
    time_scope: Literal["current_retained_state"] = "current_retained_state"
    time_range: str
    plan_metrics: SupportMetrics
    exercise_metrics: SupportMetrics
    manual_exercise_metrics: ManualMetrics
    classroom_count: int = Field(ge=0)
    adopted_plan_count: int = Field(ge=0)
    adopted_exercise_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    resource_needs: list[ResourceNeed]
    performance_state: Literal["no_data", "hidden", "available"]
    confirmed_evidence_count: int | None = Field(default=None, ge=0)
    observed_student_count: int | None = Field(default=None, ge=0)
    minimum_students: Literal[5] = 5
    hidden: bool
    explanation: str
    counting_rule: str
