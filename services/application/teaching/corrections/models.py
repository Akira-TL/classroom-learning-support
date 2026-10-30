from typing import Self

from pydantic import Field, model_validator

from ..audio.models import ReviewRequest, Utterance
from ..models import StrictModel


class CorrectionPreview(StrictModel):
    session_id: str = Field(min_length=1, max_length=80)
    segment_id: str = Field(min_length=1, max_length=80)
    review: ReviewRequest


class CorrectionApply(CorrectionPreview):
    idempotency_key: str = Field(min_length=8, max_length=100)


class ImpactCounts(StrictModel):
    evidence: int = 0
    exercises: int = 0
    plans: int = 0
    student_reports: int = 0
    parent_reports: int = 0


class CorrectionImpact(StrictModel):
    evidence_ids: list[str] = Field(default_factory=list)
    exercise_ids: list[str] = Field(default_factory=list)
    plan_ids: list[str] = Field(default_factory=list)
    student_report_ids: list[str] = Field(default_factory=list)
    parent_report_ids: list[str] = Field(default_factory=list)
    counts: ImpactCounts = Field(default_factory=ImpactCounts)

    @model_validator(mode="after")
    def calculate_counts(self) -> Self:
        counts = ImpactCounts(
            evidence=len(self.evidence_ids),
            exercises=len(self.exercise_ids),
            plans=len(self.plan_ids),
            student_reports=len(self.student_report_ids),
            parent_reports=len(self.parent_report_ids),
        )
        object.__setattr__(self, "counts", counts)
        return self


class CorrectionAssessment(StrictModel):
    current: Utterance
    impact: CorrectionImpact


class CorrectionResult(StrictModel):
    id: str
    classroom_id: str
    request: CorrectionApply
    utterance: Utterance
    impact: CorrectionImpact
