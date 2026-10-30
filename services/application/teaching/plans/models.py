from typing import Literal

from pydantic import Field

from ..learning.models import EvidenceRecord
from ..models import StrictModel, SupportDraft


class GeneratePlan(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=80)
    expected_evidence_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=100)


class PlanContent(StrictModel):
    target_student: str = Field(pattern=r"^student-[0-9]{2,4}$")
    question: str = Field(min_length=1, max_length=2000)
    preparation: str = Field(default="", max_length=2000)
    alternative: str = Field(default="", max_length=2000)
    keep_content: str = Field(default="", max_length=3000)
    activity: str = Field(min_length=1, max_length=3000)
    check_method: str = Field(min_length=1, max_length=2000)

    def complete(self) -> bool:
        return bool(self.preparation and self.alternative and self.keep_content)


class PlanTask(StrictModel):
    id: str
    classroom_id: str
    request: GeneratePlan
    basis: EvidenceRecord
    status: Literal["running", "succeeded", "failed", "stale"]
    error: str | None = None
    discarded_draft: SupportDraft | None = None


class Observation(StrictModel):
    text: str = Field(min_length=1, max_length=3000)
    teacher: str
    revision: int


class PlanRecord(StrictModel):
    id: str
    task_id: str
    classroom_id: str
    evidence_id: str
    evidence_revision: int
    original: SupportDraft
    content: PlanContent
    revision: int = 1
    status: Literal["pending", "confirmed", "rejected", "stale"] = "pending"
    reviewed_by: str | None = None
    adopted: bool = False
    adopted_by: str | None = None
    observations: list[Observation] = Field(default_factory=list)


class PlanReview(StrictModel):
    expected_revision: int = Field(ge=1)
    action: Literal["confirmed", "rejected"]
    content: PlanContent | None = None


class PlanAdoption(StrictModel):
    expected_revision: int = Field(ge=1)
    adopted: bool
    observation: str | None = Field(default=None, min_length=1, max_length=3000)


class PlanGenerationResult(StrictModel):
    task: PlanTask
    plan: PlanRecord | None = None
