"""算法对比评测：同一批合成教室数据上，团队方案 vs 未修改的基线。

指标：SI-SDR（尺度不变信号失真比，dB，越高越好），参考信号为该说话人在 mic0
上的混响语音（不考核去混响）。调参用的场景种子与本评测种子不同。

用法：uv run python scripts/benchmark.py 输出目录 [--scenes 10]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from classroom_speech.denoise import beamform_only, dual_gate_denoise, single_channel_wiener
from classroom_speech.separation import align_to_azimuth, mask_separate, selective_separate
from classroom_speech.sim import SENTENCES, VOICES, ClassroomRoom, Placement, fan_noise, scale_to_snr, synth_speech
from classroom_speech.spatial import ArrayConfig, delay_and_sum, estimate_sources, from_stft, quiet_cross_spectrum, to_stft

SEED = 2026  # 与调参种子（0–2）不同


def si_sdr(ref: np.ndarray, est: np.ndarray) -> float:
    n = min(len(ref), len(est))
    ref, est = ref[:n] - ref[:n].mean(), est[:n] - est[:n].mean()
    s = (est @ ref) / (ref @ ref) * ref
    return float(10 * np.log10(np.sum(s**2) / (np.sum((est - s) ** 2) + 1e-12)))


def summarize(values: list[float]) -> dict:
    v = np.asarray(values)
    return {"mean": round(float(v.mean()), 2), "ci95": round(float(1.96 * v.std(ddof=1) / np.sqrt(len(v))), 2), "n": len(v)}


def bench_denoise(room: ClassroomRoom, cfg: ArrayConfig, rng: np.random.Generator, scenes: int) -> dict:
    methods = {
        "原始 mic0": lambda x: x[0],
        "单通道 Wiener（基线）": lambda x: single_channel_wiener(x, cfg),
        "延迟求和波束（基线）": lambda x: beamform_only(x, cfg),
        "双门控·简单相乘（消融）": lambda x: dual_gate_denoise(x, cfg, adaptive=False)[0],
        "双门控·自适应（团队方案）": lambda x: dual_gate_denoise(x, cfg)[0],
    }
    data = []
    for i in range(scenes):
        sp = synth_speech(SENTENCES[i % len(SENTENCES)], VOICES[i % len(VOICES)])
        length = len(sp) / 16000 + 1.0
        az = rng.uniform(-70, 70)
        noise_az = -np.sign(az) * rng.uniform(40, 85)
        tgt, nz = room.render_each(
            [Placement(sp, az, rng.uniform(1.5, 4.0), 0.5), Placement(fan_noise(int(length * 16000) + 10, 16000, rng), noise_az, 3.5)], length
        )
        data.append((tgt, nz))
    out: dict = {}
    for snr in (0, 5, 10):
        scores: dict[str, list[float]] = {m: [] for m in methods}
        for tgt, nz in data:
            x = tgt + scale_to_snr(tgt, nz, snr) + 0.002 * rng.standard_normal(tgt.shape)
            for name, fn in methods.items():
                scores[name].append(si_sdr(tgt[0], fn(x)))
        out[f"{snr} dB"] = {m: summarize(v) for m, v in scores.items()}
    return out


def bench_separation(room: ClassroomRoom, cfg: ArrayConfig, rng: np.random.Generator, scenes: int) -> dict:
    scores: dict[str, list[float]] = {k: [] for k in ["混合信号", "延迟求和波束（基线）", "全程掩码分离（消融）", "选择性分离（团队方案）"]}
    az_err, aligned, found, overlap_ratio = [], 0, 0, []
    for i in range(scenes):
        a = synth_speech(SENTENCES[i % 8], VOICES[i % 4])
        b = synth_speech(SENTENCES[(i + 3) % 8], VOICES[(i + 1) % 4])
        az1, az2 = rng.uniform(-70, -10), rng.uniform(10, 70)
        offset = len(a) / 16000 * 0.5
        length = max(len(a) / 16000, offset + len(b) / 16000) + 1.0
        pre = 0.6  # 前 0.6 s 只有噪声，模拟会话中语音前的静音
        i1, i2, nz = room.render_each(
            [Placement(a, az1, 2.5, pre), Placement(b, az2, 2.5, pre + offset),
             Placement(fan_noise(int(length * 16000) + 10, 16000, rng), float(rng.choice([-85, 85])), 3.5)],
            length,
        )
        x = i1 + i2 + scale_to_snr(i1 + i2, nz, 15)
        noise_print = quiet_cross_spectrum(to_stft(x[:, : int(pre * 16000)], cfg), 100)
        spec = to_stft(x, cfg)
        est = sorted(estimate_sources(spec, cfg, max_sources=2, noise_cross=noise_print))
        if len(est) < 2:
            continue
        found += 1
        az_err += [abs(est[0] - az1), abs(est[1] - az2)]
        sel, report = selective_separate(x, est, cfg, noise_cross=noise_print)
        overlap_ratio.append(report.overlap_ratio())
        full = mask_separate(x, est, cfg)
        for k, ref in enumerate([i1[0], i2[0]]):
            scores["混合信号"].append(si_sdr(ref, x[0]))
            scores["延迟求和波束（基线）"].append(si_sdr(ref, from_stft(delay_and_sum(spec, est[k], cfg), cfg, x.shape[-1])))
            scores["全程掩码分离（消融）"].append(si_sdr(ref, full[k]))
            scores["选择性分离（团队方案）"].append(si_sdr(ref, sel[k]))
        # 方位锚定对齐：把两路参考信号打乱顺序当作“神经分离输出”，检查能否按方位还原
        shuffled = np.stack([i2[0], i1[0]])
        aligned += int(align_to_azimuth(shuffled, x, est, cfg) == [1, 0])
    return {
        "si_sdr": {m: summarize(v) for m, v in scores.items()},
        "two_speakers_found": f"{found}/{scenes}",
        "azimuth_abs_error_deg": summarize(az_err) if az_err else None,
        "alignment_correct": f"{aligned}/{found}",
        "detected_overlap_ratio": summarize(overlap_ratio) if overlap_ratio else None,
        "true_overlap_note": "第二人在第一人说到一半时开口，真实重叠约占有声时长的 1/3",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--scenes", type=int, default=10)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cfg = ArrayConfig()
    room = ClassroomRoom(cfg)
    rng = np.random.default_rng(SEED)
    t0 = time.time()
    result = {
        "data_origin": "simulated",
        "setup": {
            "room": "8×6×3 m，RT60 0.45 s（镜像法）", "mics": f"2 支，间距 {cfg.mic_distance_m} m",
            "speech": "espeak-ng 中文合成语音", "noise": "风扇/投影仪噪声点源 + 传感器白噪声", "seed": SEED,
        },
        "denoise": bench_denoise(room, cfg, rng, args.scenes),
        "separation": bench_separation(room, cfg, rng, args.scenes),
    }
    result["elapsed_s"] = round(time.time() - t0, 1)
    (args.out / "benchmark.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
