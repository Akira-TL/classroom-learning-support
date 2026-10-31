from typing import Literal, Self

from pydantic import Field, model_validator

from ..models import StrictModel

Speaker = Literal["teacher", "all", "student-01", "student-02", "student-03"]


class Transcript(StrictModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    speaker: Speaker
    text: str = Field(min_length=1, max_length=6000)


class SoundEvent(StrictModel):
    id: str = Field(min_length=1)
    part: Literal["addition", "subtraction"]
    original_start_ms: int = Field(ge=0)
    original_end_ms: int | None = Field(default=None, ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    label: str = Field(min_length=1)
    category: Literal["人声", "环境音"]

    @model_validator(mode="after")
    def aligned(self) -> Self:
        offset = -2000 if self.part == "addition" else 86000
        if self.start_ms != self.original_start_ms + offset:
            raise ValueError("事件起点未按混音时间校准")
        expected_end = None if self.original_end_ms is None else self.original_end_ms + offset
        if self.end_ms != expected_end or self.end_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError("事件终点未按混音时间校准或范围无效")
        return self


class Recording(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    audio_path: str
    duration_ms: int = Field(gt=0, le=600000)
    transcripts: list[Transcript] = Field(min_length=1)
    events: list[SoundEvent] = Field(min_length=1)

    @model_validator(mode="after")
    def ranges(self) -> Self:
        if len({event.id for event in self.events}) != len(self.events):
            raise ValueError("事件编号重复")
        if any(line.end_ms <= line.start_ms or line.end_ms > self.duration_ms for line in self.transcripts):
            raise ValueError("转写范围超出混音或起止无效")
        if any(event.start_ms >= self.duration_ms or
               event.end_ms is not None and event.end_ms > self.duration_ms for event in self.events):
            raise ValueError("声音事件超出混音范围")
        return self
