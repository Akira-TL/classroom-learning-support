"""语音侧原生协议；保留诊断 JSON 值但不将诊断当作操作指令。"""

from typing import Literal, Self

from pydantic import ConfigDict, Field, JsonValue, model_validator

from ..models import StrictModel

Reliability = Literal["usable", "needs_review", "undetermined", "failed"]


class SourceRecord(StrictModel):
    source_id: str
    kind: Literal["azimuth", "anon_speaker"]
    value: float | str
    unit: Literal["deg", "label"]
    reference: str
    valid_from_ms: int = Field(ge=0)
    valid_to_ms: int = Field(ge=0)
    reliability_state: Reliability
    rebind_hint: bool = False


class AudioRef(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,180}$")
    kind: Literal["raw", "denoised", "separated"] = "raw"
    offset_ms: int = Field(default=0, ge=0)
    note: str | None = None


class Overlap(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    present: bool
    with_segments: list[str] = Field(default_factory=list, alias="with")


class Replaces(StrictModel):
    segments: list[str]
    revisions: list[int] = Field(default_factory=list)


class Gap(StrictModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    reason: str


class NativeSpeechEvent(StrictModel):
    protocol_version: Literal["speech.v0.1"] = "speech.v0.1"
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    event_id: str = Field(min_length=1, max_length=80)
    sequence: int = Field(ge=0)
    event_type: Literal[
        "transcript.partial", "transcript.final", "transcript.revised", "transcript.retracted",
        "source.position", "audio.available", "stream.status", "session.ended",
    ]
    segment_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")
    revision: int | None = Field(default=None, ge=1)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    text: str | None = Field(default=None, max_length=6000)
    source_ref: list[str] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    audio_ref: list[AudioRef] = Field(default_factory=list)
    overlap: Overlap | None = None
    reliability_state: Reliability | None = None
    replaces: Replaces | None = None
    status: str | None = None
    gap: Gap | None = None
    resume_from_sequence: int | None = Field(default=None, ge=0)
    data_origin: Literal["live", "file_replay", "simulated"] = "live"
    diagnostics: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("结束时间不能早于开始时间")
        if self.event_type.startswith("transcript.") and not self.segment_id:
            raise ValueError("转写缺少片段标识")
        if self.gap and self.gap.end_ms < self.gap.start_ms:
            raise ValueError("缺失区间无效")
        if self.replaces and self.replaces.revisions and len(self.replaces.segments) != len(self.replaces.revisions):
            raise ValueError("替换片段和修订号数量不一致")
        return self


class NativeIngest(StrictModel):
    classroom_id: str = Field(min_length=1, max_length=80)
    event: NativeSpeechEvent
