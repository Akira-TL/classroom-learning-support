"""多人抢话评测场景：N 人注册池，其中 K 人在嘈杂教室里同时说话。

- 合成：espeak-ng 的 cmn 语音会把汉字读成字母名，改用 cmn-latn-pinyin 按拼音整句合成
  （拼音表由 pypinyin 预先生成后写死在 PINYIN 里，运行时不依赖 pypinyin）。
- 声音池：espeak-ng 拼音中文 + 不同音色变体 × 音高，最多 48 种合成音色（合成音色之间
  的差异与真实学生声音不同，结论须用真实录音复核）。
- 注册：每人在自己座位上读 2 句（与测试句不同），低噪声，带房间混响。
- 测试：K 人各说一句，开口时间在 0～1.2 s 内随机错开，叠加风扇噪声与邻班嘈杂声。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from classroom_speech.sim import ClassroomRoom, Placement, fan_noise, scale_to_snr
from classroom_speech.spatial import ArrayConfig, frame_energy_db, to_stft

VARIANTS = ["", "m1", "m2", "m3", "m4", "m5", "m6", "m7", "f1", "f2", "f3", "f4", "f5", "Andy", "Annie", "Belinda",
            "Linda", "Michael", "Paul", "Steph", "anika", "edward", "max", "norbert"]
PITCHES = [35, 75]

ENROLL_SENTENCES = [
    "今天我们一起学习分数的初步认识。",
    "我把这张纸对折两次，得到四个小正方形。",
    "我觉得这个答案还需要再检查一下。",
]
TEST_SENTENCES = [
    "有四块就是四分之一。", "不对，要分得一样大才是四分之一。", "老师，我觉得这一块比较大。",
    "把一个圆平均分成四份，每份是它的四分之一。", "这两块不一样大，所以不能说是二分之一。",
    "我同意他的说法，要先平均分。", "四分之一比二分之一小。", "这个图形没有平均分。",
    "十分之一比四分之一还要小。", "我们组分出来的是八分之一。",
]
PRE_S = 0.6

PINYIN = {
    "今天我们一起学习分数的初步认识。": "jin1 tian1 wo3 men yi4 qi3 xue2 xi2 fen1 shu4 de chu1 bu4 ren4 shi2",
    "我把这张纸对折两次，得到四个小正方形。": "wo3 ba3 zhe4 zhang1 zhi3 dui4 zhe2 liang3 ci4 de2 dao4 si4 ge4 xiao3 zheng4 fang1 xing2",
    "我觉得这个答案还需要再检查一下。": "wo3 jue2 de zhe4 ge da2 an4 hai2 xu1 yao4 zai4 jian3 cha2 yi1 xia4",
    "有四块就是四分之一。": "you3 si4 kuai4 jiu4 shi4 si4 fen1 zhi1 yi1",
    "不对，要分得一样大才是四分之一。": "bu2 dui4 yao4 fen1 de yi1 yang4 da4 cai2 shi4 si4 fen1 zhi1 yi1",
    "老师，我觉得这一块比较大。": "lao3 shi1 wo3 jue2 de zhe4 yi1 kuai4 bi3 jiao4 da4",
    "把一个圆平均分成四份，每份是它的四分之一。": "ba3 yi2 ge4 yuan2 ping2 jun1 fen1 cheng2 si4 fen4 mei3 fen4 shi4 ta1 de si4 fen1 zhi1 yi1",
    "这两块不一样大，所以不能说是二分之一。": "zhe4 liang3 kuai4 bu4 yi2 yang4 da4 suo3 yi3 bu4 neng2 shuo1 shi4 er4 fen1 zhi1 yi1",
    "我同意他的说法，要先平均分。": "wo3 tong2 yi4 ta1 de shuo1 fa3 yao4 xian1 ping2 jun1 fen1",
    "四分之一比二分之一小。": "si4 fen1 zhi1 yi1 bi3 er4 fen1 zhi1 yi1 xiao3",
    "这个图形没有平均分。": "zhe4 ge tu2 xing2 mei2 you3 ping2 jun1 fen1",
    "十分之一比四分之一还要小。": "shi2 fen1 zhi1 yi1 bi3 si4 fen1 zhi1 yi1 hai2 yao4 xiao3",
    "我们组分出来的是八分之一。": "wo3 men zu3 fen4 chu1 lai2 de shi4 ba1 fen1 zhi1 yi1",
}


def synth_speech(text: str, voice: dict, sample_rate: int = 16000) -> np.ndarray:
    """按拼音整句合成一句中文（voice["voice"] 需为 cmn-latn-pinyin 及其变体），返回单声道 float32。"""
    if shutil.which("espeak-ng") is None:
        raise RuntimeError("需要安装 espeak-ng 才能生成合成语音（apt install espeak-ng）")
    name = voice["voice"] if voice["voice"].startswith("cmn-latn-pinyin") else voice["voice"].replace("cmn", "cmn-latn-pinyin", 1)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "s.wav"
        subprocess.run(["espeak-ng", "-v", name, "-p", str(voice["pitch"]), "-s", str(voice["speed"]), "-w", str(out),
                        PINYIN[text]], check=True, capture_output=True)
        audio, sr = sf.read(out, dtype="float32")
    g = np.gcd(sr, sample_rate)
    audio = resample_poly(audio, sample_rate // g, sr // g).astype(np.float32)
    return audio / (np.max(np.abs(audio)) + 1e-9) * 0.5


def voice_pool(n: int) -> list[dict]:
    pool = [{"voice": f"cmn-latn-pinyin+{v}" if v else "cmn-latn-pinyin", "pitch": p, "speed": 145 + 10 * (i % 3)}
            for p in PITCHES for i, v in enumerate(VARIANTS)]
    return pool[:n]


def activity_truth(images: list[np.ndarray], cfg: ArrayConfig, rel_db: float = -28.0) -> np.ndarray:
    acts = []
    for img in images:
        e = np.convolve(frame_energy_db(to_stft(img, cfg)), np.ones(5) / 5, mode="same")
        acts.append(e > np.percentile(e, 99) + rel_db)
    return np.stack(acts)


def seats(n: int, rng: np.random.Generator) -> list[tuple[float, float]]:
    """n 个座位（方位°, 距离 m），在 −75°～75° 内大致均匀，带随机扰动。"""
    az = np.linspace(-75, 75, n) + rng.uniform(-6, 6, n) if n > 1 else np.array([rng.uniform(-60, 60)])
    return [(float(np.clip(a, -80, 80)), float(rng.uniform(1.5, 4.0 if abs(a) < 55 else 3.2))) for a in rng.permutation(az)]


def babble(n: int, rng: np.random.Generator, voices: list[dict]) -> np.ndarray:
    """邻班/走廊嘈杂声：几句不在注册池里的低通混合人声，循环铺满。"""
    parts = [synth_speech(TEST_SENTENCES[j], v) for j, v in enumerate(voices)]
    out = np.zeros(n, np.float32)
    for p in parts:
        start = rng.integers(0, max(n - len(p), 1))
        seg = np.tile(p, int(np.ceil(n / len(p))) + 1)[: n]
        out += np.roll(seg, start)
    return out / (np.std(out) + 1e-9)


def build_pool(n: int, rng: np.random.Generator, room: ClassroomRoom) -> list[dict]:
    voices = voice_pool(n)
    pool = []
    for k, (v, (az, dist)) in enumerate(zip(voices, seats(n, rng))):
        clips = [synth_speech(s, v) for s in ENROLL_SENTENCES[:2]]
        dry = np.concatenate([clips[0], np.zeros(4000, np.float32), clips[1]])
        length = len(dry) / 16000 + 0.5
        img, nz = room.render_each([Placement(dry, az, dist, 0.2), Placement(fan_noise(int(length * 16000) + 10, 16000, rng), 85.0, 3.5)], length)
        pool.append({"id": f"S{k + 1:02d}", "voice": v, "azimuth": az, "distance": dist,
                     "enroll": (img + scale_to_snr(img, nz, 25)).astype(np.float32)})
    return pool


def make_mixture(pool: list[dict], active: list[int], rng: np.random.Generator, room: ClassroomRoom, cfg: ArrayConfig,
                 snr_db: float = 5.0, babble_voices: list[dict] | None = None) -> dict:
    sents = rng.permutation(len(TEST_SENTENCES))[: len(active)]
    sigs = [synth_speech(TEST_SENTENCES[s], pool[k]["voice"]) for s, k in zip(sents, active)]
    offs = [0.0] + list(rng.uniform(0.2, 1.2, len(active) - 1))
    length = PRE_S + max(o + len(s) / 16000 for o, s in zip(offs, sigs)) + 0.6
    n = int(length * 16000) + 10
    places = [Placement(s, pool[k]["azimuth"], pool[k]["distance"], PRE_S + o) for s, o, k in zip(sigs, offs, active)]
    noise_src = [Placement(fan_noise(n, 16000, rng), float(rng.choice([-85, 85])), 3.5)]
    if babble_voices:
        noise_src.append(Placement(babble(n, rng, babble_voices), float(rng.uniform(-40, 40)), 4.5))
    imgs = room.render_each(places + noise_src, length)
    speech, noises = imgs[: len(active)], imgs[len(active):]
    total = sum(speech)
    noise = sum(scale_to_snr(total, nz, snr_db + 10 * np.log10(len(noises))) for nz in noises)
    x = total + noise + 0.002 * rng.standard_normal(total.shape)
    return {"x": x.astype(np.float32), "refs": np.stack([s[0] for s in speech]), "active": list(active),
            "texts": [TEST_SENTENCES[s] for s in sents], "truth": activity_truth(speech, cfg), "offsets": offs}
