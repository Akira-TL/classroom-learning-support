"""应用内部语音草案，不表示语音供应方已确认协议。"""

from typing import Literal, Self

from pydantic import Field, model_validator

from ..models import StrictModel


class SpeechEvent(StrictModel):
    protocol_version: Literal["app-draft-1"] = "app-draft-1"
    session_id: str = Field(min_length=1, max_length=80)
    event_id: str = Field(min_length=1, max_length=80)
    sequence: int = Field(ge=0)
    event_type: Literal["partial", "final", "revision", "withdraw", "status", "end"]
    source_kind: Literal["synthetic", "recorded_result", "upstream_live"]
    segment_id: str | None = Field(default=None, min_length=1, max_length=80)
    revision: int = Field(default=1, ge=1)
    start_ms: int = Field(default=0, ge=0)
    end_ms: int = Field(default=0, ge=0)
    text: str | None = Field(default=None, min_length=1, max_length=6000)
    source_ref: str | None = Field(default=None, max_length=100)
    overlap: bool = False
    status: Literal["running", "paused", "disconnected", "ended"] | None = None
    gap_start_ms: int | None = Field(default=None, ge=0)
    gap_end_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_payload(self) -> Self:
        if self.end_ms < self.start_ms:
            raise ValueError("结束时间不能早于开始时间")
        if self.event_type in {"partial", "final", "revision", "withdraw"} and not self.segment_id:
            raise ValueError("发言事件缺少片段标识")
        if self.event_type in {"partial", "final", "revision"} and not self.text:
            raise ValueError("转写事件不能缺少文字")
        if self.event_type == "status" and not self.status:
            raise ValueError("状态事件缺少状态")
        if (self.gap_start_ms is None) != (self.gap_end_ms is None):
            raise ValueError("缺失区间需要完整时间范围")
        if self.gap_start_ms is not None and self.gap_end_ms < self.gap_start_ms:
            raise ValueError("缺失区间无效")
        return self


class Utterance(StrictModel):
    session_id: str
    segment_id: str
    revision: int
    sequence: int
    phase: Literal["partial", "final", "revision", "withdraw"]
    source_kind: Literal["synthetic", "recorded_result", "upstream_live"]
    start_ms: int
    end_ms: int
    upstream_text: str
    source_ref: str | None = None
    overlap: bool = False
    version: int = 1
    teacher_text: str | None = None
    student_alias: str | None = None
    question_id: str | None = None
    text_review: Literal["pending", "confirmed", "unable"] = "pending"
    identity_review: Literal["pending", "confirmed", "unable"] = "pending"
    question_review: Literal["pending", "confirmed", "unable"] = "pending"
    reviewed_by: str | None = None
    audio_available: bool = False
