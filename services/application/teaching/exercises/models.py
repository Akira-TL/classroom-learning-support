from typing import Literal, Self

from pydantic import Field, model_validator

from ..learning.models import EvidenceRecord
from ..models import Exercise, StrictModel, SupportDraft


class GenerateExercises(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=80)
    expected_evidence_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=100)


class ExerciseTask(StrictModel):
    id: str
    classroom_id: str
    request: GenerateExercises
    basis: EvidenceRecord
    status: Literal["running", "succeeded", "failed", "stale"]
    error: str | None = None
    discarded_draft: SupportDraft | None = None


class ExerciseRecord(StrictModel):
    id: str
    task_id: str
    classroom_id: str
    evidence_id: str
    evidence_revision: int
    original: SupportDraft
    exercises: list[Exercise]
    revision: int = 1
    status: Literal["pending", "confirmed", "rejected", "stale"] = "pending"
    reviewed_by: str | None = None
    adopted: bool = False
    adopted_by: str | None = None


class ExerciseReview(StrictModel):
    expected_revision: int = Field(ge=1)
    action: Literal["pending", "confirmed", "rejected"]
    exercises: list[Exercise] | None = Field(default=None, min_length=3, max_length=3)

    @model_validator(mode="after")
    def unique_levels(self) -> Self:
        if self.exercises is not None and {item.level for item in self.exercises} != {
            "concept",
            "explanation",
            "transfer",
        }:
            raise ValueError("练习必须各覆盖一个层次")
        return self


class ExerciseAdoption(StrictModel):
    expected_revision: int = Field(ge=1)
    adopted: bool


class ExerciseGenerationResult(StrictModel):
    task: ExerciseTask
    exercise_set: ExerciseRecord | None = None
