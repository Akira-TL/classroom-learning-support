from typing import Literal

from pydantic import Field

from ...models import StrictModel
from ..models import CompareRequest, Observation
from ..tags.models import TagBatch, TagComparison

Perspective = Literal["teacher", "head_teacher", "student", "parent", "teaching_director"]


class ExplainRequest(StrictModel):
    comparison: CompareRequest
    perspective: Perspective = "teacher"


class ExplainContent(StrictModel):
    change_explanation: str = Field(min_length=1, max_length=5000)
    followup_questions: list[str] = Field(min_length=1, max_length=10)
    summary: str = Field(min_length=1, max_length=3000)
    followup: str = Field(min_length=1, max_length=3000)


class ExplanationView(StrictModel):
    id: str
    classroom_id: str
    student_id: str
    perspective: Perspective
    source_fingerprint: str
    model: str
    status: Literal["generated"] = "generated"
    content: ExplainContent
    comparison: TagComparison


class RecipientExplanation(StrictModel):
    id: str
    student_id: str
    perspective: Literal["student", "parent"]
    source_fingerprint: str
    model: str
    content: ExplainContent
    status: Literal["generated"] = "generated"


class StudentHistory(StrictModel):
    student_id: str
    tag_batches: list[TagBatch]
    observations: list[Observation]
