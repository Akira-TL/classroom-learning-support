"""方向二评测：三证会审门控（TEG）vs 基准方案，含压力场景与消融。

场景（均为合成教室，RT60 0.45 s，双麦 8 cm）：
- std     与 scripts/benchmark.py 相同的分布：风扇在说话人另一侧。
- trap    噪声源与说话人同向（相差 5–15°），空间线索几乎无用。
- burst   稳态风扇 + 说话中途才开口的邻座同学（静音段的噪声指纹里没有他）。
- wrong   与 std 相同的数据，但给所有方案的目标方位偏 35°（模拟定位失误）。
- stale   与 std 相同的数据，但噪声指纹是在风扇更响（+6 dB）时采的（风扇后来调小了）。
指标：SI-SDR（dB），参考为 mic0 上的混响语音。调参种子 7，评测种子 2026。

用法：uv run python scripts/bench_denoise.py 输出目录 [--scenes 12] [--seed 2026]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from classroom_speech.denoise import dual_gate_denoise, single_channel_wiener, target_direction
from classroom_speech.denoise_v2 import TriGateConfig, adaptive_denoise
from classroom_speech.sim import SENTENCES, VOICES, ClassroomRoom, Placement, fan_noise, scale_to_snr, synth_speech
from classroom_speech.spatial import ArrayConfig, to_stft

SNRS = (-5, 0, 5, 10)
PRE_S = 0.5  # 说话前的静音，流水线在这里采噪声指纹


def si_sdr(ref: np.ndarray, est: np.ndarray) -> float:
    n = min(len(ref), len(est))
    ref, est = ref[:n] - ref[:n].mean(), est[:n] - est[:n].mean()
    s = (est @ ref) / (ref @ ref) * ref
    return float(10 * np.log10(np.sum(s**2) / (np.sum((est - s) ** 2) + 1e-12)))


def summarize(values: list[float]) -> dict:
    v = np.asarray(values)
    return {"mean": round(float(v.mean()), 2), "ci95": round(float(1.96 * v.std(ddof=1) / np.sqrt(len(v))), 2), "n": len(v)}


def make_scenes(kind: str, room: ClassroomRoom, rng: np.random.Generator, scenes: int) -> list[tuple[np.ndarray, np.ndarray]]:
    out = []
    for i in range(scenes):
        sp = synth_speech(SENTENCES[i % len(SENTENCES)], VOICES[i % len(VOICES)])
        length = len(sp) / 16000 + 1.0
        n = int(length * 16000) + 10
        az = rng.uniform(-70, 70)
        if kind == "trap":
            noise_az = float(np.clip(az + rng.choice([-1, 1]) * rng.uniform(5, 15), -88, 88))
            others = [Placement(fan_noise(n, 16000, rng), noise_az, 3.5)]
        elif kind == "burst":
            other = synth_speech(SENTENCES[(i + 3) % 8], VOICES[(i + 1) % 4])
            others = [
                Placement(other, -np.sign(az) * rng.uniform(35, 80), 2.0, PRE_S + 0.3 * len(sp) / 16000),
                Placement(0.5 * fan_noise(n, 16000, rng), float(rng.choice([-85, 85])), 3.5),
            ]
        else:
            others = [Placement(fan_noise(n, 16000, rng), -np.sign(az) * rng.uniform(40, 85), 3.5)]
        imgs = room.render_each([Placement(sp, az, rng.uniform(1.5, 4.0), PRE_S)] + others, length)
        out.append((imgs[0], sum(imgs[1:])))
    return out


def noise_print(x: np.ndarray, cfg: ArrayConfig) -> np.ndarray:
    """静音段 mic0 平均功率谱：流水线的噪声指纹。"""
    return np.mean(np.abs(to_stft(x[:1, : int(PRE_S * cfg.sample_rate)], cfg)[0]) ** 2, axis=1)


def methods(cfg: ArrayConfig) -> dict:
    full = TriGateConfig()
    return {
        "原始 mic0": lambda x, th, npw: x[0],
        "单通道 Wiener（基线）": lambda x, th, npw: single_channel_wiener(x, cfg),
        "双门控·简单相乘（旧消融）": lambda x, th, npw: dual_gate_denoise(x, cfg, theta_deg=th, adaptive=False)[0],
        "双门控·自适应（旧方案）": lambda x, th, npw: dual_gate_denoise(x, cfg, theta_deg=th)[0],
        "三证会审门控（新方案）": lambda x, th, npw: adaptive_denoise(x, cfg, theta_deg=th, noise_power=npw, tcfg=full)[0],
        "消融：去掉噪声指纹锚定": lambda x, th, npw: adaptive_denoise(
            x, cfg, theta_deg=th, noise_power=npw, tcfg=TriGateConfig(anchor_noise=False))[0],
        "消融：空间门强制上场（无自检）": lambda x, th, npw: adaptive_denoise(
            x, cfg, theta_deg=th, noise_power=npw, tcfg=TriGateConfig(self_check=False, a_max=3.0, snr_mid_db=3.0))[0],
        "消融：去掉保真护栏": lambda x, th, npw: adaptive_denoise(
            x, cfg, theta_deg=th, noise_power=npw, tcfg=TriGateConfig(print_guard=np.inf))[0],
    }


def run(scenes: int = 12, seed: int = 2026) -> dict:
    cfg = ArrayConfig()
    room = ClassroomRoom(cfg)
    rng = np.random.default_rng(seed)
    t0 = time.time()
    data = {k: make_scenes(k, room, rng, scenes) for k in ("std", "trap", "burst")}
    data["wrong"], data["stale"] = data["std"], data["std"]
    fns = methods(cfg)
    result: dict = {}
    spatial_on: dict = {}
    for kind, items in data.items():
        result[kind] = {}
        for snr in SNRS:
            nrng = np.random.default_rng(seed + snr + 100)
            scores: dict[str, list[float]] = {m: [] for m in fns}
            on = 0
            for tgt, nz in items:
                noise = scale_to_snr(tgt, nz, snr)
                x = tgt + noise + 0.002 * nrng.standard_normal(tgt.shape)
                th = target_direction(to_stft(x, cfg), cfg)
                if kind == "wrong":
                    th = th + 35.0 if th < 0 else th - 35.0
                npw = noise_print(x, cfg)
                if kind == "stale":  # 指纹采于风扇更响时：+6 dB
                    npw = npw * 4.0
                for name, fn in fns.items():
                    scores[name].append(si_sdr(tgt[0], fn(x, th, npw)))
                on += adaptive_denoise(x, cfg, theta_deg=th, noise_power=npw)[1]["spatial_gate"] != "off"
            result[kind][f"{snr} dB"] = {m: summarize(v) for m, v in scores.items()}
            spatial_on[f"{kind} {snr} dB"] = f"{on}/{len(items)}"
    return {
        "data_origin": "simulated",
        "setup": {"room": "8×6×3 m，RT60 0.45 s（镜像法）", "mics": f"2 支，间距 {cfg.mic_distance_m} m",
                  "speech": "espeak-ng 中文合成语音", "metric": "SI-SDR（dB），参考为 mic0 混响语音", "seed": seed,
                  "tuning_seed": 7},
        "scenarios": {"std": "风扇在说话人另一侧（同 benchmark.py）", "trap": "噪声与说话人同向（差 5–15°）",
                      "burst": "说话中途邻座插话 + 风扇", "wrong": "目标方位偏 35°", "stale": "噪声指纹过时（采于噪声大 6 dB 时）"},
        "results": result,
        "tri_gate_spatial_gate_on": spatial_on,
        "elapsed_s": round(time.time() - t0, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--scenes", type=int, default=12)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    res = run(args.scenes, args.seed)
    (args.out / "bench_denoise.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
    for kind, by in res["results"].items():
        print(f"== {kind}")
        for snr, ms in by.items():
            print(f"{snr:>6} " + "  ".join(f"{m[:10]}:{v['mean']:6.2f}" for m, v in ms.items()))


if __name__ == "__main__":
    main()
