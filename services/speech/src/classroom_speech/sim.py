"""合成教室数据：espeak-ng 中文合成语音（经带调拼音发音） + pyroomacoustics 镜像法房间混响。

只用于算法对比与演示，所有输出都应标注“合成数据”。语音由开源合成引擎
生成，音色机械，不代表真实儿童课堂；真实录音到位后用同一评测脚本复跑。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyroomacoustics as pra
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfilt

from .spatial import ArrayConfig

SENTENCES = [
    "有四块就是四分之一。",
    "不对，要分得一样大才是四分之一。",
    "老师，我觉得这一块比较大。",
    "把一个圆平均分成四份，每份是它的四分之一。",
    "这两块不一样大，所以不能说是二分之一。",
    "我同意他的说法，要先平均分。",
    "四分之一比二分之一小。",
    "这个图形没有平均分。",
]

VOICES = [
    {"voice": "cmn", "pitch": 40, "speed": 150},
    {"voice": "cmn+f3", "pitch": 70, "speed": 160},
    {"voice": "cmn+m3", "pitch": 30, "speed": 140},
    {"voice": "cmn+f4", "pitch": 85, "speed": 170},
]


def to_pinyin(text: str) -> str:
    """汉字 → 带调拼音（tone3），标点保留为停顿。"""
    from pypinyin import Style, lazy_pinyin

    out = []
    for tok in lazy_pinyin(text, style=Style.TONE3, neutral_tone_with_five=True):
        out.append("," if all(c in "，。？！、；：,.?!" for c in tok) else tok.replace("5", ""))
    return " ".join(out)


def synth_speech(text: str, voice: dict, sample_rate: int = 16000) -> np.ndarray:
    """用 espeak-ng 合成一句中文，返回单声道 float32。

    先转带调拼音再用 cmn-latn-pinyin 发音：直接用 cmn 声音时 espeak-ng 会把“四”“一”等字
    按英文读（four / one），合成语音里的数学关键词就不对了。
    """
    if shutil.which("espeak-ng") is None:
        raise RuntimeError("需要安装 espeak-ng 才能生成合成语音（apt install espeak-ng）")
    variant = voice["voice"].partition("+")[2]
    name = "cmn-latn-pinyin" + (f"+{variant}" if variant else "")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "s.wav"
        subprocess.run(
            ["espeak-ng", "-v", name, "-p", str(voice["pitch"]), "-s", str(voice["speed"]), "-w", str(out), to_pinyin(text)],
            check=True,
            capture_output=True,
        )
        audio, sr = sf.read(out, dtype="float32")
    g = np.gcd(sr, sample_rate)
    audio = resample_poly(audio, sample_rate // g, sr // g).astype(np.float32)
    return audio / (np.max(np.abs(audio)) + 1e-9) * 0.5


def fan_noise(n: int, sample_rate: int, rng: np.random.Generator) -> np.ndarray:
    """风扇 / 投影仪噪声：低频嗡声 + 带通宽带噪声。"""
    t = np.arange(n) / sample_rate
    hum = sum(0.3 / k * np.sin(2 * np.pi * 100 * k * t + rng.uniform(0, 6.28)) for k in range(1, 5))
    sos = butter(4, [150, 3500], btype="band", fs=sample_rate, output="sos")
    broad = sosfilt(sos, rng.standard_normal(n))
    x = hum + broad / np.std(broad)
    return (x / np.std(x)).astype(np.float32)


@dataclass
class Placement:
    signal: np.ndarray
    azimuth_deg: float
    distance_m: float
    offset_s: float = 0.0


@dataclass
class ClassroomRoom:
    """8 m × 6 m × 3 m 教室，阵列位于前方中央 1.2 m 高。"""

    cfg: ArrayConfig = field(default_factory=ArrayConfig)
    dims: tuple[float, float, float] = (8.0, 6.0, 3.0)
    rt60_s: float = 0.45
    center: tuple[float, float, float] = (4.0, 1.0, 1.2)

    def _room(self) -> pra.ShoeBox:
        absorption, max_order = pra.inverse_sabine(self.rt60_s, self.dims)
        room = pra.ShoeBox(
            self.dims, fs=self.cfg.sample_rate, materials=pra.Material(absorption), max_order=min(max_order, 17)
        )
        c, h = np.array(self.center), self.cfg.mic_distance_m / 2
        mics = np.array([c + [h, 0, 0], c - [h, 0, 0]]).T  # mic0 在 +x 侧
        room.add_microphone_array(mics)
        return room

    def position(self, azimuth_deg: float, distance_m: float, height: float = 1.1) -> list[float]:
        a = np.deg2rad(azimuth_deg)
        c = self.center
        return [c[0] + distance_m * np.sin(a), c[1] + distance_m * np.cos(a), height]

    def render_each(self, placements: list[Placement], length_s: float) -> list[np.ndarray]:
        """分别渲染每个声源到两路麦克风，返回每个声源的 (2, N) 图像，便于做参考信号。"""
        n = int(length_s * self.cfg.sample_rate)
        images = []
        for p in placements:
            room = self._room()
            room.add_source(self.position(p.azimuth_deg, p.distance_m), signal=p.signal, delay=p.offset_s)
            room.simulate()
            sig = room.mic_array.signals[:, :n]
            images.append(np.pad(sig, ((0, 0), (0, n - sig.shape[1]))).astype(np.float32))
        return images


def scale_to_snr(target: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    pt, pn = np.mean(target[0] ** 2), np.mean(noise[0] ** 2) + 1e-12
    return noise * np.sqrt(pt / (pn * 10 ** (snr_db / 10)))
