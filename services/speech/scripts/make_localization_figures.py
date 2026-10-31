"""方向一展示图：① 混响把方位“压扁”与孪生反扭回去；② 一节课的说话人跟踪时间线（基准 vs 团队方案）。

用法：uv run python scripts/make_localization_figures.py 输出目录 [--seed 2026]
所有图均为合成数据，标题注明。
"""

from __future__ import annotations

import argparse
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import bench_localization as B  # noqa: E402

from classroom_speech.localization import SpeakerTracker, default_dewarp, localize  # noqa: E402
from classroom_speech.spatial import ArrayConfig, estimate_sources  # noqa: E402
from classroom_speech.stages import BaselineTracker  # noqa: E402

plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei", "Microsoft YaHei", "SimHei", "PingFang SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
INK, MUTED, BASE, OURS, ACCENT = "#1f2328", "#6e7781", "#c4432b", "#1f6feb", "#8250df"


def fig_dewarp(out: Path, seed: int, n: int = 60) -> dict:
    cfg = ArrayConfig()
    with Pool(4) as p:
        scenes = p.map(B.make_scene, [("one", lv, i, seed, B.NOMINAL_DIMS, B.NOMINAL_CENTER) for lv in ("mild", "harsh") for i in range(n // 2)])
    pts = []
    for s in scenes:
        spec, nc, npsd = B._prep(s["x"], s["pre"], cfg)
        b = estimate_sources(spec, cfg, max_sources=1, noise_cross=nc)
        o = localize(spec, cfg, nc, 1, noise_psd=npsd).azimuths
        pts.append((s["az"][0], b[0] if b else np.nan, o[0] if o else np.nan))
    pts = np.asarray(pts)
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.6), dpi=150)
    ax = axes[0]
    ax.plot([-90, 90], [-90, 90], color=MUTED, lw=1, ls="--", label="理想：测得 = 真实")
    ax.scatter(pts[:, 0], pts[:, 1], s=16, color=BASE, alpha=0.75, label=f"基准 SRP-PHAT（误差 {np.nanmean(np.abs(pts[:, 1] - pts[:, 0])):.1f}°）")
    ax.scatter(pts[:, 0], pts[:, 2], s=16, color=OURS, alpha=0.85, label=f"团队方案（误差 {np.nanmean(np.abs(pts[:, 2] - pts[:, 0])):.1f}°）")
    ax.set_xlabel("学生真实方位（°）")
    ax.set_ylabel("系统测得方位（°）")
    ax.set_xlim(-85, 85)
    ax.set_ylim(-85, 85)
    ax.set_title("混响把方位“压”向正前方，孪生把它扭回来", loc="left", fontsize=11)
    ax.legend(fontsize=8, loc="upper left", frameon=False)
    ax = axes[1]
    curve = default_dewarp()
    m = np.linspace(-80, 80, 161)
    ax.plot(m, curve(m), color=ACCENT, lw=2)
    ax.plot([-90, 90], [-90, 90], color=MUTED, lw=1, ls="--")
    ax.set_xlabel("起音加权 + 扩散补偿后测得的方位（°）")
    ax.set_ylabel("反扭后的方位（°）")
    ax.set_title("数字孪生学到的“反畸变曲线”（标称 8×6×3 m 教室）", loc="left", fontsize=11)
    ax.set_xlim(-80, 80)
    ax.set_ylim(-80, 80)
    for a in axes:
        a.grid(alpha=0.25)
    fig.suptitle("合成数据：RT60 0.3–0.9 s，教室尺寸与阵列位置存在测量误差（mild/harsh）", fontsize=9, color=MUTED, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(out / "loc_dewarp.png")
    plt.close(fig)
    return {"n": len(pts), "baseline_mae": round(float(np.nanmean(np.abs(pts[:, 1] - pts[:, 0]))), 2),
            "ours_mae": round(float(np.nanmean(np.abs(pts[:, 2] - pts[:, 0]))), 2)}


def fig_tracking(out: Path, seed: int, lesson_idx: int = 0) -> dict:
    cfg = ArrayConfig()
    lesson = B.make_lesson((lesson_idx, seed))
    rows = []
    base_t, ours_t = BaselineTracker(), SpeakerTracker()
    for j, u in enumerate(lesson["utts"]):
        spec, nc, npsd = B._prep(u["x"], 0.6, cfg)
        b = estimate_sources(spec, cfg, max_sources=1, noise_cross=nc)
        r = localize(spec, cfg, nc, 1, noise_psd=npsd)
        bl = base_t.assign(b[0] if b else 0.0, j * 5000).label
        d = ours_t.assign(r.azimuths[0], j * 5000, j * 5000 + 3000, u["x"][0, 9600:], 16000, r.confidence[0])
        rows.append({"utt": j + 1, "true_speaker": f"学生{chr(65 + u['speaker'])}", "true_az": round(u["az"], 1),
                     "baseline_az": b[0] if b else None, "baseline_label": bl, "ours_az": r.azimuths[0], "ours_conf": r.confidence[0],
                     "ours_label": d.label, "rebind_hint": bool(d.rebind_hint), "possible_rebind_of": d.diagnostics.get("possible_rebind_of"), "reliability": d.reliability, "reason": d.diagnostics.get("reason"),
                     "front_back": bool(u["front_back"]), "moved": bool(u["moved"])})
    # 合成整节课音频（单声道 mic0，依次拼接）便于现场播放
    audio = np.concatenate([np.concatenate([u["x"][0, 9600:], np.zeros(4000, np.float32)]) for u in lesson["utts"]])
    sf.write(out / "loc_tracking_lesson.wav", audio / (np.abs(audio).max() + 1e-9) * 0.8, 16000)
    fig, axes = plt.subplots(3, 1, figsize=(10.5, 6.4), dpi=150, sharex=True)
    names = sorted({r["true_speaker"] for r in rows})
    palette = ["#1f6feb", "#c4432b", "#1a7f37", "#8250df", "#bf8700", "#0e7c86", "#cf222e", "#57606a"]
    for ax, key, title in ((axes[0], "true_speaker", "真实说话人"), (axes[1], "baseline_label", "基准：只按方位归并"),
                           (axes[2], "ours_label", "团队方案：方位 × 声纹联合")):
        labels = sorted({r[key] for r in rows})
        for r in rows:
            k = labels.index(r[key])
            az = r["true_az"] if key == "true_speaker" else (r["baseline_az"] if key == "baseline_label" else r["ours_az"])
            ax.scatter(r["utt"], az, s=150, color=palette[k % len(palette)], edgecolor="white", zorder=3)
            ax.text(r["utt"], az, r[key].replace("spk_0", "").replace("spk_", "").replace("学生", ""), ha="center", va="center",
                    fontsize=7, color="white", zorder=4)
            if r["moved"]:
                ax.scatter(r["utt"], az, s=320, facecolor="none", edgecolor=INK, lw=1.2, zorder=2)
        ax.set_ylabel("方位（°）")
        ax.set_ylim(-85, 85)
        ax.grid(alpha=0.2)
        n_lab = len(labels)
        ax.set_title(f"{title}（{n_lab} 个标签）", loc="left", fontsize=10)
    axes[2].set_xlabel("第几句发言（黑圈 = 换座后发言；A、B 前后排坐在同一方向）")
    fig.suptitle("合成数据：一节 14 句的小组讨论", fontsize=9, color=MUTED, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(out / "loc_tracking_timeline.png")
    plt.close(fig)
    (out / "loc_tracking_lesson.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    return {"utterances": len(rows), "true_speakers": len(names),
            "baseline_labels": len({r["baseline_label"] for r in rows}), "ours_labels": len({r["ours_label"] for r in rows})}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--lesson", type=int, default=0)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"dewarp": fig_dewarp(a.out, a.seed), "tracking": fig_tracking(a.out, a.seed, a.lesson)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
