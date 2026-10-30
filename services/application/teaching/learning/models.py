from typing import Literal

from pydantic import Field

from ..models import EvidenceContent, EvidenceDraft, StrictModel, VerifiedContext


class GenerateEvidence(StrictModel):
    session_id: str = Field(min_length=1, max_length=80)
    segment_id: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=100)


class ManualEvidenceRequest(GenerateEvidence):
    content: EvidenceContent


class EvidenceBasis(StrictModel):
    session_id: str
    segment_id: str
    utterance_version: int
    question_fingerprint: str
    context: VerifiedContext


class EvidenceTask(StrictModel):
    id: str
    classroom_id: str
    request: GenerateEvidence
    basis: EvidenceBasis
    status: Literal["running", "succeeded", "failed", "stale"]
    error: str | None = None
    discarded_draft: EvidenceDraft | None = None
    origin: Literal["deepseek", "teacher_manual"] = "deepseek"
    manual_content: EvidenceContent | None = None


class EvidenceRecord(StrictModel):
    id: str
    task_id: str
    classroom_id: str
    basis: EvidenceBasis
    original: EvidenceDraft
    content: EvidenceContent
    revision: int = 1
    status: Literal["pending", "confirmed", "rejected", "stale"] = "pending"
    reviewed_by: str | None = None


class EvidenceReview(StrictModel):
    expected_revision: int = Field(ge=1)
    action: Literal["confirmed", "rejected"]
    content: EvidenceContent | None = None


class GenerationResult(StrictModel):
    task: EvidenceTask
    evidence: EvidenceRecord | None = None
