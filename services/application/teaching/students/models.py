from datetime import datetime
from typing import Literal

from pydantic import Field

from ..models import Exercise, StrictModel


class StudentPublishPreview(StrictModel):
    exercise_set_id: str = Field(min_length=1, max_length=80)
    expected_exercise_revision: int = Field(ge=1)
    student_id: str = Field(pattern=r"^student-[0-9]{2,4}$")
    feedback: str = Field(min_length=1, max_length=6000)


class StudentPublish(StudentPublishPreview):
    idempotency_key: str = Field(min_length=8, max_length=100)


class ReportPreview(StrictModel):
    student_id: str
    feedback: str
    exercises: list[Exercise]


class ReportSummary(StrictModel):
    id: str
    classroom_id: str
    student_id: str
    revision: int
    published_at: datetime
    status: Literal["published", "revoked", "stale"]


class ReportRecord(ReportSummary):
    teacher_id: str
    exercise_set_id: str
    exercise_revision: int
    feedback: str
    exercises: list[Exercise]


class ReportView(ReportSummary):
    feedback: str
    exercises: list[Exercise]


class RevokeReport(StrictModel):
    expected_revision: int = Field(ge=1)


class StudentFeedbackRequest(StrictModel):
    kind: Literal["exercise_feedback", "correction"]
    text: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=8, max_length=100)


class FeedbackRecord(StrictModel):
    id: str
    classroom_id: str
    report_id: str
    report_revision: int
    student_id: str
    kind: Literal["exercise_feedback", "correction"]
    text: str
    revision: int = 1
    status: Literal["open", "accepted", "rejected", "answered"] = "open"
    response: str | None = None
    handled_by: str | None = None


class HandleFeedback(StrictModel):
    expected_revision: int = Field(ge=1)
    status: Literal["accepted", "rejected", "answered"]
    response: str = Field(min_length=1, max_length=4000)
