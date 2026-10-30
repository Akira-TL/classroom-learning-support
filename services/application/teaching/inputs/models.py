from typing import Literal

from pydantic import ConfigDict, Field

from ..audio.media import AudioAsset
from ..models import StrictModel


class CreateInput(StrictModel):
    input_mode: Literal["microphone", "file_stream"]
    sample_rate: int = Field(strict=True, ge=8000, le=48000)
    channels: int = Field(strict=True, ge=1, le=1)
    encoding: Literal["pcm_s16le"]


class InputSession(CreateInput):
    id: str
    classroom_id: str
    processing_mode: Literal["capture_only"] = "capture_only"
    recognizer_connected: Literal[False] = False
    status: Literal["recording", "paused", "finishing", "ended", "failed"] = "recording"
    received_samples: int = 0
    expected_sequence: int = 0
    audio_asset: AudioAsset | None = None
    error: str | None = None


class InputFrame(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)
    sequence: int = Field(strict=True, ge=0)
    start_sample: int = Field(strict=True, ge=0)
    frame_count: int = Field(strict=True, ge=1, le=32768)
    pcm_base64: str = Field(min_length=1, max_length=87400)


class InputState(StrictModel):
    action: Literal["pause", "resume"]


class FinishInput(StrictModel):
    interrupted: bool = Field(default=False, strict=True)
