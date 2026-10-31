"""带样本游标的音频帧写入；重试不会重复执行识别。"""

import base64
import binascii
import hashlib
import threading
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

class AudioSession(Protocol):
    ended: bool

    def push_pcm(self, pcm: bytes, channels: int = 2) -> None: ...


class InputFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(strict=True, ge=0)
    start_sample: int = Field(strict=True, ge=0)
    frame_count: int = Field(strict=True, ge=1, le=32768)
    pcm_base64: str = Field(min_length=1, max_length=87400)


class FrameReceipt(BaseModel):
    expected_sequence: int
    received_samples: int


class FrameConflict(ValueError):
    pass


class FrameReceiver:
    def __init__(self, session: AudioSession, channels: int) -> None:
        self.session, self.channels = session, channels
        self._lock = threading.Lock()
        self._digests: dict[int, str] = {}
        self._samples = 0

    def accept(self, frame: InputFrame) -> FrameReceipt:
        try:
            pcm = base64.b64decode(frame.pcm_base64, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError("PCM帧不是有效的Base64") from error
        if len(pcm) != frame.frame_count * self.channels * 2 or len(pcm) > 65536:
            raise ValueError("PCM帧长度与通道数和样本数不符，或超过65536字节")
        digest = hashlib.sha256(frame.model_dump_json().encode()).hexdigest()
        with self._lock:
            previous = self._digests.get(frame.sequence)
            if previous is not None:
                if previous != digest:
                    raise FrameConflict("同一帧序号不能使用不同内容")
                return FrameReceipt(expected_sequence=len(self._digests), received_samples=self._samples)
            if self.session.ended:
                raise FrameConflict("会话已结束")
            if frame.sequence != len(self._digests) or frame.start_sample != self._samples:
                raise FrameConflict("音频帧序号或样本游标不连续")
            self.session.push_pcm(pcm, self.channels)
            self._samples += frame.frame_count
            self._digests[frame.sequence] = digest
            return FrameReceipt(expected_sequence=len(self._digests), received_samples=self._samples)
