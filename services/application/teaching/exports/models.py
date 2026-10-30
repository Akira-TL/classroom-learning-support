from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from ..classroom.classrooms import Classroom
from ..learning.models import EvidenceRecord
from ..models import StrictModel
from ..plans.models import PlanRecord
from ..reports.models import ParentReport


class CreateExport(StrictModel):
    plan_id: str = Field(min_length=1, max_length=80)
    expected_plan_revision: int = Field(ge=1)
    parent_report_id: str | None = Field(default=None, min_length=1, max_length=80)
    expected_parent_revision: int | None = Field(default=None, ge=1)
    idempotency_key: str = Field(min_length=8, max_length=100)

    @model_validator(mode="after")
    def paired_parent(self) -> Self:
        if (self.parent_report_id is None) != (self.expected_parent_revision is None):
            raise ValueError("家长报告标识和版本须同时提供")
        return self


class ExportMetadata(StrictModel):
    id: str
    revision: int
    created_at: datetime
    status: Literal["active", "revoked", "stale", "deleted"]


class ExportRecord(StrictModel):
    id: str
    classroom_id: str
    teacher_id: str
    request: CreateExport


class ExportSources(StrictModel):
    classroom: Classroom
    evidence: EvidenceRecord
    plan: PlanRecord
    parent: ParentReport | None = None


class RevokeExport(StrictModel):
    expected_revision: int = Field(ge=1)
