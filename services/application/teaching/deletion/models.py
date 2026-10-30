from datetime import datetime
from typing import Literal

from pydantic import Field

from ..models import StrictModel


class DeleteClassroom(StrictModel):
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=100)
    confirmation: str = Field(min_length=1, max_length=200)


class Resource(StrictModel):
    kind: Literal["audio", "export"]
    id: str


class DeletionTask(StrictModel):
    id: str
    classroom_id: str
    teacher_id: str
    revision: int = 1
    created_at: datetime
    local_status: Literal["pending", "complete", "failed"] = "pending"
    external_status: Literal["not_requested"] = "not_requested"
    remaining: list[Resource] = Field(default_factory=list)
    error: str | None = None


class DeletionView(StrictModel):
    id: str
    classroom_id: str
    revision: int
    created_at: datetime
    local_status: Literal["pending", "complete", "failed"]
    local_complete: bool
    external_status: Literal["not_requested"]
    external_pending: bool = True
    remaining_files: int
    error: str | None = None
    notice: str = "本机受控内容已停止提供；供应方删除尚未请求，已下载离线副本无法远程收回。"
