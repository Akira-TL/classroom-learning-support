"""语音模块对外事件协议 speech.v0.1（对应 docs/integration/语音模块对接契约.md §3）。

这是语音侧对契约提案的首版实现，待应用侧确认后冻结为 v1。
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

PROTOCOL_VERSION = "speech.v0.1"


class EventType(str, Enum):
    TRANSCRIPT_PARTIAL = "transcript.partial"
    TRANSCRIPT_FINAL = "transcript.final"
    TRANSCRIPT_REVISED = "transcript.revised"
    TRANSCRIPT_RETRACTED = "transcript.retracted"
    SOURCE_POSITION = "source.position"
    AUDIO_AVAILABLE = "audio.available"
    STREAM_STATUS = "stream.status"
    SESSION_ENDED = "session.ended"


class Reliability(str, Enum):
    USABLE = "usable"
    NEEDS_REVIEW = "needs_review"
    UNDETERMINED = "undetermined"
    FAILED = "failed"


class SourceRecord(BaseModel):
    """声源线索。方位与匿名说话人分开记录，不混成一个字符串。"""

    source_id: str
    kind: Literal["azimuth", "anon_speaker"]
    value: float | str
    unit: Literal["deg", "label"]
    reference: str = Field(description="azimuth 为 mic_pair_broadside；anon_speaker 为 session")
    valid_from_ms: int
    valid_to_ms: int
    reliability_state: Reliability
    rebind_hint: bool = False


class AudioRef(BaseModel):
    id: str
    kind: Literal["raw", "denoised", "separated"] = "raw"
    offset_ms: int = 0
    note: str | None = None


class Overlap(BaseModel):
    present: bool
    with_segments: list[str] = Field(default_factory=list, alias="with")

    model_config = {"populate_by_name": True}


class Replaces(BaseModel):
    segments: list[str]
    revisions: list[int] = Field(default_factory=list)


class Gap(BaseModel):
    start_ms: int
    end_ms: int
    reason: str


class SpeechEvent(BaseModel):
    protocol_version: str = PROTOCOL_VERSION
    session_id: str
    event_id: str
    sequence: int
    event_type: EventType
    segment_id: str | None = None
    revision: int | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    text: str | None = Field(default=None, description="无转写事件不填；不用空字符串暗示识别成功")
    source_ref: list[str] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    audio_ref: list[AudioRef] = Field(default_factory=list)
    overlap: Overlap | None = None
    reliability_state: Reliability | None = None
    replaces: Replaces | None = None
    status: str | None = None
    gap: Gap | None = None
    resume_from_sequence: int | None = None
    data_origin: Literal["live", "file_replay", "simulated"] = "live"
    diagnostics: dict | None = Field(default=None, description="模型分数等诊断信息，应用不据此做判断")
