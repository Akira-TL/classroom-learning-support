"""现成能力的适配器：转写（FunASR / 思必驰）与神经去噪、分离（ClearerVoice）。

这些模型在首次运行时从 ModelScope / HuggingFace 下载权重，需要联网与 GPU。
未安装或加载失败时返回 None，由流水线发出“不可用”状态，不伪造识别结果。
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import soundfile as sf

log = logging.getLogger(__name__)

CLASSROOM_HOTWORDS = "平均分 四分之一 二分之一 三分之一 分数 分母 分子 一样大 等分"


@dataclass
class AsrResult:
    text: str
    engine: str


class AsrEngine(Protocol):
    name: str

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> AsrResult | None: ...


class FunAsrEngine:
    """FunASR 离线 Paraformer-large + 标点，支持课堂数学热词。"""

    name = "funasr-paraformer-zh"

    def __init__(self, hotwords: str = CLASSROOM_HOTWORDS, device: str = "cuda:0") -> None:
        from funasr import AutoModel  # 延迟导入：可选依赖

        self.hotwords = hotwords
        self.model = AutoModel(model="paraformer-zh", punc_model="ct-punc", device=device, disable_update=True)

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> AsrResult | None:
        if sample_rate != 16000:
            raise ValueError("FunASR 需要 16 kHz 输入")
        res = self.model.generate(input=audio.astype(np.float32), hotword=self.hotwords)
        text = (res[0].get("text") or "").strip() if res else ""
        return AsrResult(text=text, engine=self.name) if text else None


class FunAsrStreamingEngine:
    """FunASR Paraformer 流式模型，用于临时结果（每 600 ms 一块）。"""

    name = "funasr-paraformer-zh-streaming"
    chunk_size = [0, 10, 5]

    def __init__(self, device: str = "cuda:0") -> None:
        from funasr import AutoModel

        self.model = AutoModel(model="paraformer-zh-streaming", device=device, disable_update=True)

    def new_cache(self) -> dict:
        return {}

    def feed(self, chunk: np.ndarray, cache: dict, is_final: bool) -> str:
        res = self.model.generate(
            input=chunk.astype(np.float32),
            cache=cache,
            is_final=is_final,
            chunk_size=self.chunk_size,
            encoder_chunk_look_back=4,
            decoder_chunk_look_back=1,
        )
        return (res[0].get("text") or "") if res else ""


class AiSpeechEngine:
    """思必驰转写适配位。

    接口地址、鉴权方式和请求格式须按团队所持思必驰产品的官方文档填写，
    凭证通过环境变量传入，不写入仓库。未配置时不可用。
    """

    name = "aispeech"

    def __init__(self) -> None:
        raise NotImplementedError("思必驰接口待按实际产品文档接入：在此实现 transcribe()，凭证读环境变量")

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> AsrResult | None:  # pragma: no cover
        raise NotImplementedError


class ClearerVoiceSeparator:
    """ClearerVoice MossFormer2_SS_16K 两人分离。输出顺序任意，须用 align_to_azimuth 对齐。"""

    name = "clearervoice-mossformer2-ss-16k"

    def __init__(self) -> None:
        from clearvoice import ClearVoice

        self.cv = ClearVoice(task="speech_separation", model_names=["MossFormer2_SS_16K"])

    def separate(self, mono: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mix.wav"
            sf.write(path, mono, sample_rate)
            out = self.cv(input_path=str(path), online_write=False)
        arr = np.asarray(out[0] if isinstance(out, (list, tuple)) else out, dtype=np.float32)
        return arr.reshape(-1, arr.shape[-1])


class ClearerVoiceEnhancer:
    """ClearerVoice FRCRN_SE_16K 神经去噪，可接在双门控之后。"""

    name = "clearervoice-frcrn-se-16k"

    def __init__(self) -> None:
        from clearvoice import ClearVoice

        self.cv = ClearVoice(task="speech_enhancement", model_names=["FRCRN_SE_16K"])

    def enhance(self, mono: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "in.wav"
            sf.write(path, mono, sample_rate)
            out = self.cv(input_path=str(path), online_write=False)
        return np.asarray(out, dtype=np.float32).reshape(-1)[: len(mono)]


def try_load(factory, label: str):
    """加载可选引擎，失败时记录原因并返回 None。"""
    try:
        return factory()
    except Exception as exc:  # noqa: BLE001 — 任何加载失败都应降级为“不可用”
        log.warning("%s 不可用：%s", label, exc)
        return None
