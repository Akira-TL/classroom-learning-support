from datetime import datetime
from typing import Literal

from pydantic import Field

from ..models import StrictModel


class PreviewRequest(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=80)
    expected_evidence_revision: int = Field(ge=1)
    student_id: str = Field(pattern=r"^student-[0-9]{2,4}$")
    summary: str = Field(min_length=1, max_length=4000)
    home_activity: str = Field(min_length=1, max_length=4000)


class PublishRequest(PreviewRequest):
    idempotency_key: str = Field(min_length=8, max_length=100)


class ReportPreview(StrictModel):
    content: PreviewRequest
    parent_id: str
    notice: str = "请核对学生、文字与家庭活动，确认后发布；不含原音频，离线副本不能远程收回。"


class ParentReport(StrictModel):
    id: str
    classroom_id: str
    parent_id: str
    student_id: str
    teacher_id: str
    revision: int = 1
    status: Literal["published", "revoked", "stale"] = "published"
    published_at: datetime
    content: PreviewRequest


class ReportView(StrictModel):
    id: str
    classroom_id: str
    student_id: str
    revision: int
    status: Literal["published", "revoked", "stale"]
    published_at: datetime
    summary: str | None = None
    home_activity: str | None = None
    evidence_id: str
    evidence_revision: int


class RevokeRequest(StrictModel):
    expected_revision: int = Field(ge=1)


class QuestionRequest(StrictModel):
    text: str = Field(min_length=1, max_length=3000)
    idempotency_key: str = Field(min_length=8, max_length=100)


class ParentQuestion(StrictModel):
    id: str
    report_id: str
    classroom_id: str
    parent_id: str
    text: str
    status: Literal["open", "answered", "dismissed"] = "open"
    response: str | None = None
    revision: int = 1


class ResolveQuestion(StrictModel):
    expected_revision: int = Field(ge=1)
    status: Literal["answered", "dismissed"]
    response: str = Field(min_length=1, max_length=3000)
