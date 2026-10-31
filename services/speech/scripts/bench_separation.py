"""方向三评测：声纹注册的选择性多人分离（ESS）vs 基准方案。

三组实验（全部合成数据，评测种子与调参种子不同）：
  A. 同时说话人数曲线：注册池 10 人，K = 2/3/5/8 人同时说话（风扇 + 邻班嘈杂声，5 dB）。
  B. 注册池规模曲线：K = 3，注册池 N = 5/10/20/40 人，考核“认人”与分离。
  C. 单人片段是否被误伤：两人抢话场景中，只统计真值为“单人说话”的片段的 SI-SDR。

SI-SDRi = 输出 SI-SDR − 混合信号 SI-SDR（dB，越高越好）。参考信号为该说话人在
mic0 上的混响语音。没认出来的人按“输出混合信号”计（SI-SDRi = 0）。

用法：uv run python scripts/bench_separation.py 输出目录 [--scenes 6] [--workers 4]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from crowd_scenes import PRE_S, build_pool, make_mixture  # noqa: E402

from classroom_speech.enrolled import EnrollConfig, enroll, enrolled_separate  # noqa: E402
from classroom_speech.separation import detect_overlap, mask_separate, selective_separate  # noqa: E402
from classroom_speech.sim import ClassroomRoom  # noqa: E402
from classroom_speech.spatial import ArrayConfig, from_stft, quiet_cross_spectrum, to_stft  # noqa: E402

SEED = 2026
BABBLE = [{"voice": "cmn+klatt", "pitch": 55, "speed": 170}, {"voice": "cmn+Iven", "pitch": 60, "speed": 160}]
METHODS = ["空间掩码（基线）", "基准选择性分离", "ESS·已知谁在说（上限）", "ESS·全自动（团队方案）", "理想掩码（理论上限）"]


def si_sdr(ref: np.ndarray, est: np.ndarray) -> float:
    n = min(len(ref), len(est))
    ref, est = ref[:n] - ref[:n].mean(), est[:n] - est[:n].mean()
    if not np.any(est):
        return float("nan")
    s = (est @ ref) / (ref @ ref) * ref
    return float(10 * np.log10(np.sum(s**2) / (np.sum((est - s) ** 2) + 1e-12)))


def summarize(values: list[float]) -> dict | None:
    v = np.asarray([x for x in values if np.isfinite(x)])
    if len(v) < 2:
        return None
    return {"mean": round(float(v.mean()), 2), "ci95": round(float(1.96 * v.std(ddof=1) / np.sqrt(len(v))), 2), "n": int(len(v))}


def frames_to_samples(mask: np.ndarray, cfg: ArrayConfig, n: int) -> np.ndarray:
    return np.repeat(mask, cfg.hop)[:n] if len(mask) * cfg.hop >= n else np.pad(np.repeat(mask, cfg.hop), (0, n - len(mask) * cfg.hop))


def eval_mixture(job: tuple) -> dict:
    mix, profiles, seats, cfg, save_dir, tag = job
    x, refs, active = mix["x"], mix["refs"], mix["active"]
    k = len(active)
    pre = x[:, : int(PRE_S * cfg.sample_rate)]
    noise_cross = quiet_cross_spectrum(to_stft(pre, cfg), 100)
    t0 = time.time()
    outs: dict[str, np.ndarray] = {}
    azs = [seats[i] for i in active]
    outs["空间掩码（基线）"] = mask_separate(x, azs, cfg)
    outs["基准选择性分离"] = selective_separate(x, sorted(azs), cfg, noise_cross=noise_cross)[0][np.argsort(np.argsort(azs))]
    outs["ESS·已知谁在说（上限）"] = enrolled_separate(x, profiles, cfg, noise_ref=pre, known_active=active)[0]
    t1 = time.time()
    streams, found, rep = enrolled_separate(x, profiles, cfg, noise_ref=pre)
    runtime = time.time() - t1
    outs["ESS·全自动（团队方案）"] = np.stack([streams[found.index(i)] if i in found else x[0] for i in active])
    spec = to_stft(x, cfg)[0]
    ref_spec = to_stft(refs, cfg)
    mag = np.abs(ref_spec)
    irm = mag / (mag.sum(axis=0) + np.abs(spec - ref_spec.sum(axis=0)) + 1e-9)
    outs["理想掩码（理论上限）"] = np.stack([from_stft(spec * irm[j], cfg, x.shape[1]) for j in range(k)])
    nonsel = enrolled_separate(x, profiles, cfg, noise_ref=pre, selective=False, known_active=active)[0]

    base = [si_sdr(refs[j], x[0]) for j in range(k)]
    res = {"K": k, "mixture_si_sdr": base, "si_sdri": {m: [si_sdr(refs[j], outs[m][j]) - base[j] for j in range(k)] for m in METHODS}}
    res["runtime_s"] = runtime
    res["audio_s"] = x.shape[1] / cfg.sample_rate
    res["ident"] = {"true": sorted(map(int, active)), "found": sorted(map(int, found)), "gains": rep.gains}

    # 重叠检测（逐帧）：真值 = 两人及以上同时有声
    truth = mix["truth"]
    t = min(truth.shape[1], len(rep.frame_counts))
    speech_t = truth[:, :t].any(axis=0)
    gt = truth[:, :t].sum(axis=0) >= 2
    pred = rep.frame_counts[:t] >= 2
    base_rep = detect_overlap(to_stft(x, cfg), cfg, noise_cross=noise_cross)
    fps = cfg.sample_rate / cfg.hop
    base_pred = np.zeros(t, bool)
    for w in base_rep.windows:
        if w["overlap"]:
            base_pred[int(w["start_ms"] / 1000 * fps): int(w["end_ms"] / 1000 * fps)] = True

    def prf(p: np.ndarray) -> dict:
        p = p & speech_t
        tp, fp, fn = int((p & gt).sum()), int((p & ~gt).sum()), int((~p & gt & speech_t).sum())
        return {"tp": tp, "fp": fp, "fn": fn}

    res["overlap"] = {"ESS": prf(pred), "基准": prf(base_pred), "true_ratio": float(gt.sum() / max(speech_t.sum(), 1)),
                      "separated_ratio": float((pred & speech_t).sum() / max(speech_t.sum(), 1))}

    # 单人片段误伤：只看真值单人区（该说话人独自有声）的样本
    solo = {}
    for name, sig in [("不做选择（全程分离）", nonsel), ("选择性（团队方案）", outs["ESS·已知谁在说（上限）"])]:
        vals = []
        for j in range(k):
            only_j = truth[j, :t] & (truth[:, :t].sum(axis=0) == 1)
            if only_j.sum() < 20:
                continue
            m = frames_to_samples(only_j, cfg, x.shape[1]).astype(bool)
            vals.append(si_sdr(refs[j][m], sig[j][m]) - si_sdr(refs[j][m], x[0][m]))
        solo[name] = vals
    res["solo_si_sdri"] = solo
    res["elapsed_s"] = time.time() - t0
    if save_dir is not None:
        # 供转写评测（scripts/asr_cer.py）使用：参考 / 混合 / 空间基线 / ESS 各一份
        import soundfile as sf

        save_dir.mkdir(parents=True, exist_ok=True)
        entries = []
        for j in range(k):
            files = {}
            for name, sig in [("reference", refs[j]), ("mixture", x[0]), ("spatial", outs["空间掩码（基线）"][j]),
                              ("ess", outs["ESS·全自动（团队方案）"][j])]:
                f = save_dir / f"{tag}_s{j}_{name}.wav"
                sf.write(f, (sig / (np.max(np.abs(sig)) + 1e-9) * 0.9).astype(np.float32), cfg.sample_rate)
                files[name] = f.name
            entries.append({"K": k, "text": mix["texts"][j], "files": files, "identified": int(active[j]) in found})
        res["audio_manifest"] = entries
    return res


def make_jobs(n_pool: int, ks: list[int], scenes: int, seed: int, cfg: ArrayConfig, save_dir: Path | None = None,
              save_max_k: int = 5) -> tuple[list, list]:
    rng = np.random.default_rng(seed)
    room = ClassroomRoom(cfg)
    pool = build_pool(n_pool, rng, room)
    profiles = [enroll(p["id"], p["enroll"], cfg, EnrollConfig(learn_iters=60), seed=i) for i, p in enumerate(pool)]
    seats = [p["azimuth"] for p in pool]
    mixes = []
    for k in ks:
        for _ in range(scenes):
            act = [int(a) for a in rng.choice(n_pool, k, replace=False)]
            mixes.append(make_mixture(pool, act, rng, room, cfg, 5.0, BABBLE))
    return [(m, profiles, seats, cfg, save_dir if len(m["active"]) <= save_max_k else None, f"n{n_pool}_m{i:02d}")
            for i, m in enumerate(mixes)], mixes


def aggregate(results: list[dict]) -> dict:
    out = {m: summarize(sum((r["si_sdri"][m] for r in results), [])) for m in METHODS}
    exact = sum(r["ident"]["true"] == r["ident"]["found"] for r in results)
    tp = sum(len(set(r["ident"]["true"]) & set(r["ident"]["found"])) for r in results)
    n_true = sum(len(r["ident"]["true"]) for r in results)
    n_found = sum(len(r["ident"]["found"]) for r in results)
    ov = {}
    for name in ("ESS", "基准"):
        tp_, fp_, fn_ = (sum(r["overlap"][name][key] for r in results) for key in ("tp", "fp", "fn"))
        p, rc = tp_ / max(tp_ + fp_, 1), tp_ / max(tp_ + fn_, 1)
        ov[name] = {"precision": round(p, 3), "recall": round(rc, 3), "f1": round(2 * p * rc / max(p + rc, 1e-9), 3)}
    return {
        "si_sdri_db": out,
        "mixture_si_sdr_db": summarize(sum((r["mixture_si_sdr"] for r in results), [])),
        "identification": {"exact_set": f"{exact}/{len(results)}", "recall": round(tp / max(n_true, 1), 3),
                           "precision": round(tp / max(n_found, 1), 3)},
        "overlap_detection_frame": ov,
        "true_overlap_ratio": round(float(np.mean([r["overlap"]["true_ratio"] for r in results])), 3),
        "separated_ratio": round(float(np.mean([r["overlap"]["separated_ratio"] for r in results])), 3),
        "solo_region_si_sdri_db": {k: summarize(sum((r["solo_si_sdri"][k] for r in results), []))
                                   for k in results[0]["solo_si_sdri"]},
        "real_time_factor": round(float(sum(r["runtime_s"] for r in results) / sum(r["audio_s"] for r in results)), 2),
        "scenes": len(results),
    }


def run(scenes: int = 6, seed: int = SEED, workers: int = 4, ks: tuple[int, ...] = (2, 3, 5, 8),
        pools: tuple[int, ...] = (5, 10, 20, 40), save_audio: Path | None = None) -> dict:
    cfg = ArrayConfig()
    t0 = time.time()
    result: dict = {
        "data_origin": "simulated",
        "setup": {"room": "8×6×3 m，RT60 0.45 s（镜像法）", "mics": f"2 支，间距 {cfg.mic_distance_m} m",
                  "speech": "espeak-ng 拼音整句合成中文（cmn-latn-pinyin），48 种音色变体；注册 2 句，测试句与注册句不同",
                  "noise": "风扇点源 + 邻班嘈杂人声（不在注册池中），总 SNR 5 dB", "seed": seed},
        "by_speakers": {}, "by_pool": {},
    }
    with ProcessPoolExecutor(workers) as ex:
        jobs, _ = make_jobs(10, list(ks), scenes, seed, cfg, save_audio)
        res = list(ex.map(eval_mixture, jobs))
        if save_audio is not None:
            manifest = sum((r.get("audio_manifest", []) for r in res), [])
            (save_audio / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
        for k in ks:
            result["by_speakers"][str(k)] = aggregate([r for r in res if r["K"] == k])
            print(k, json.dumps(result["by_speakers"][str(k)]["si_sdri_db"], ensure_ascii=False), flush=True)
        for n in pools:
            jobs, _ = make_jobs(n, [3], scenes, seed + n, cfg)
            result["by_pool"][str(n)] = aggregate(list(ex.map(eval_mixture, jobs)))
            print("pool", n, json.dumps(result["by_pool"][str(n)]["identification"], ensure_ascii=False), flush=True)
    result["elapsed_s"] = round(time.time() - t0, 1)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--scenes", type=int, default=6)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--speakers", default="2,3,5,8")
    ap.add_argument("--pools", default="5,10,20,40")
    ap.add_argument("--save-audio", type=Path, default=None, help="保存 K≤5 场景的音频，供 asr_cer.py 测字错率")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    result = run(args.scenes, SEED, args.workers, tuple(int(k) for k in args.speakers.split(",")),
                 tuple(int(n) for n in args.pools.split(",")), args.save_audio)
    (args.out / "bench_separation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
