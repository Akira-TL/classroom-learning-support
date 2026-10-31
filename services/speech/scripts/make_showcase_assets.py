"""生成展示材料：对合成课堂片段做去噪与分离，导出前后对照音频与频谱图。

用法：uv run python scripts/make_showcase_assets.py demo目录 输出目录
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf

from classroom_speech.denoise import dual_gate_denoise, single_channel_wiener
from classroom_speech.separation import selective_separate
from classroom_speech.spatial import ArrayConfig, estimate_sources, quiet_cross_spectrum, to_stft

plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei", "Microsoft YaHei", "SimHei", "PingFang SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def spectrogram(ax, y: np.ndarray, title: str, cfg: ArrayConfig, t0: float = 0.0) -> None:
    spec = np.abs(to_stft(y[None], cfg)[0])
    db = 20 * np.log10(spec + 1e-6)
    ax.imshow(db, origin="lower", aspect="auto", cmap="magma", vmin=db.max() - 70, vmax=db.max(),
              extent=[t0, t0 + len(y) / cfg.sample_rate, 0, cfg.sample_rate / 2000])
    ax.set_title(title, fontsize=11, loc="left")
    ax.set_ylabel("kHz")


def main(demo: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cfg = ArrayConfig()
    x, sr = sf.read(demo / "demo_scene.wav", dtype="float32")
    x = x.T
    meta = json.loads((demo / "demo_scene.json").read_text())
    first = min(line["start_s"] for line in meta["lines"])
    noise_print = quiet_cross_spectrum(to_stft(x[:, : int((first - 0.1) * sr)], cfg), 100)

    # 去噪展示：取教师单人发言段（流水线也是按单人片段去噪，多人片段走分离）
    t = [ln for ln in meta["lines"] if ln["speaker"] == "教师"][0]
    c0 = max(t["start_s"] - 0.4, 0.0)
    clip = x[:, int(c0 * sr) : int((t["end_s"] + 0.4) * sr)]
    wiener = single_channel_wiener(clip, cfg)
    ours, diag = dual_gate_denoise(clip, cfg)
    sf.write(out / "01_raw_mic0.wav", clip[0], sr)
    sf.write(out / "02_wiener_baseline.wav", wiener, sr)
    sf.write(out / "03_dual_gate_ours.wav", ours, sr)

    fig, axes = plt.subplots(3, 1, figsize=(9, 6.5), sharex=True)
    spectrogram(axes[0], clip[0], "原始音频（mic0，风扇噪声 SNR 5 dB）", cfg, c0)
    spectrogram(axes[1], wiener, "基线：单通道 Wiener 去噪", cfg, c0)
    spectrogram(axes[2], ours, "团队方案：空间—频谱双门控去噪", cfg, c0)
    axes[2].set_xlabel("时间（秒）")
    fig.tight_layout()
    fig.savefig(out / "denoise_spectrogram.png", dpi=90)

    # 重叠段：学生甲与学生乙抢话
    a = [ln for ln in meta["lines"] if ln["speaker"] == "学生甲"][0]
    b = [ln for ln in meta["lines"] if ln["speaker"] == "学生乙"][0]
    s0, s1 = a["start_s"] - 0.2, b["end_s"] + 0.2
    seg = x[:, int(s0 * sr) : int(s1 * sr)]
    az = sorted(estimate_sources(to_stft(seg, cfg), cfg, max_sources=2, noise_cross=noise_print))
    streams, report = selective_separate(seg, az, cfg, noise_cross=noise_print)
    sf.write(out / "04_overlap_mix.wav", seg[0], sr)
    for k, angle in enumerate(az):
        sf.write(out / f"05_separated_{k}_{int(round(angle))}deg.wav", streams[k], sr)
    fig, axes = plt.subplots(len(az) + 1, 1, figsize=(9, 6.5), sharex=True)
    spectrogram(axes[0], seg[0], "重叠片段：两名学生同时发言（混合）", cfg, s0)
    for k, angle in enumerate(az):
        spectrogram(axes[k + 1], streams[k], f"方位锚定分离：{angle:+.0f}° 方向一路", cfg, s0)
    for w in report.windows:
        if w["overlap"]:
            axes[0].axvspan(s0 + w["start_ms"] / 1000, s0 + w["end_ms"] / 1000, color="#38bdf8", alpha=0.08)
    axes[-1].set_xlabel("时间（秒）")
    fig.tight_layout()
    fig.savefig(out / "separation_spectrogram.png", dpi=90)

    summary = {
        "data_origin": "simulated",
        "denoise_target_azimuth_deg": diag["target_azimuth_deg"],
        "overlap_segment_s": [round(s0, 2), round(s1, 2)],
        "estimated_azimuths_deg": az,
        "true_azimuths_deg": [a["azimuth_deg"], b["azimuth_deg"]],
        "overlap_windows": [w for w in report.windows if w["overlap"]],
    }
    (out / "showcase.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False)[:600])


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
