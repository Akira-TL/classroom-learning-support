"""教学输入与结果的明确类型；模型输出始终是待教师核验的草稿。"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class VerifiedContext(StrictModel):
    question_id: str = Field(min_length=1, max_length=80)
    question_revision: int = Field(ge=1)
    objective: str = Field(min_length=1, max_length=2000)
    question: str = Field(min_length=1, max_length=6000)
    reference_answer: str = Field(min_length=1, max_length=6000)
    diagram_required: bool = False
    diagram_description: str | None = Field(default=None, min_length=1, max_length=4000)
    utterance_id: str = Field(min_length=1, max_length=80)
    utterance_revision: int = Field(ge=1)
    student_alias: str = Field(pattern=r"^student-[0-9]{2,4}$")
    utterance: str = Field(min_length=1, max_length=6000)
    text_confirmed: Literal[True]
    identity_confirmed: Literal[True]
    question_confirmed: Literal[True]

    @model_validator(mode="after")
    def require_diagram_context(self) -> Self:
        if self.diagram_required and not self.diagram_description:
            raise ValueError("题目需要图形说明，补充并核验后才能分析")
        return self


class EvidenceContent(StrictModel):
    quote: str = Field(min_length=1, max_length=6000)
    interpretation: str = Field(min_length=1, max_length=3000)
    limitation: str = Field(min_length=1, max_length=2000)
    follow_up_question: str = Field(min_length=1, max_length=1000)


class EvidenceDraft(StrictModel):
    context: VerifiedContext
    content: EvidenceContent
    model: str
    status: Literal["pending_teacher_review"] = "pending_teacher_review"


class ConfirmedEvidence(StrictModel):
    draft: EvidenceDraft
    teacher_confirmed: Literal[True]


class Exercise(StrictModel):
    level: Literal["concept", "explanation", "transfer"]
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=2000)
    explanation: str = Field(min_length=1, max_length=3000)


class SupportContent(StrictModel):
    exercises: list[Exercise] = Field(min_length=3, max_length=3)
    classroom_question: str = Field(min_length=1, max_length=2000)
    next_lesson: str = Field(min_length=1, max_length=3000)
    check_method: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def each_level_once(self) -> Self:
        if {item.level for item in self.exercises} != {"concept", "explanation", "transfer"}:
            raise ValueError("三道练习应各覆盖一个层次")
        return self


class SupportDraft(StrictModel):
    evidence: ConfirmedEvidence
    content: SupportContent
    model: str
    status: Literal["pending_teacher_review"] = "pending_teacher_review"
