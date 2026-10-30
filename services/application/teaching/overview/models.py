from typing import Literal

from pydantic import Field

from ..models import StrictModel


class ResourceNeed(StrictModel):
    kind: Literal["exercise_materials", "teaching_activities"]
    description: str
    count: int = Field(ge=0)


class AdminSummary(StrictModel):
    scope: str
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
