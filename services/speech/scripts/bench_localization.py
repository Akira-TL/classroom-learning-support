"""方向一评测：混响鲁棒定位 + 方位×声纹联合跟踪，与基准同条件对比。

三组实验（全部为合成数据，data_origin=simulated）：
1. 失配混响定位：RT60 随机 0.3–0.9 s，真实教室与标称尺寸存在测量误差（exact / mild ±0.25 m / harsh ±0.6 m，
   阵列位置同时偏移），单人与双人重叠两类场景。漏检按 90° 计误差，防止靠少报刷分。
2. 官方 benchmark 同款场景（scripts/benchmark.py 的双人重叠设置），只换方位估计。
3. 说话人跟踪：整节课 14 句轮流发言，含“前后排同方向不同人”与“中途换座”，看匿名标签纯度 / 覆盖。

用法：
  uv run python scripts/bench_localization.py out_dir [--scenes 12] [--seed 2026]
  uv run python scripts/bench_localization.py calibrate [--dims 8,6,3 --center 4,1,1.2]   # 为某间教室生成反畸变曲线
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from classroom_speech.localization import IDENTITY, DewarpCurve, SpeakerTracker, localize
from classroom_speech.stages import BaselineTracker
from classroom_speech.sim import SENTENCES, VOICES, ClassroomRoom, Placement, fan_noise, scale_to_snr, synth_speech
from classroom_speech.spatial import ArrayConfig, estimate_sources, quiet_cross_spectrum, to_stft

NOMINAL_DIMS, NOMINAL_CENTER = (8.0, 6.0, 3.0), (4.0, 1.0, 1.2)
LEVELS = {"exact": (0.0, 0.0), "mild": (0.25, 0.1), "harsh": (0.6, 0.25)}


def summarize(values) -> dict:
    v = np.asarray(values, float)
    ci = float(1.96 * v.std(ddof=1) / np.sqrt(len(v))) if len(v) > 1 else 0.0
    return {"mean": round(float(v.mean()), 2), "median": round(float(np.median(v)), 2), "ci95": round(ci, 2), "n": len(v)}


# ---------- 场景 ----------
def _room(rng, level, dims=NOMINAL_DIMS, center=NOMINAL_CENTER):
    jd, jc = LEVELS[level]
    d = tuple(np.array(dims) + rng.uniform(-jd, jd, 3) * [1, 1, 0.5])
    c = tuple(np.array(center) + rng.uniform(-jc, jc, 3) * [1, 1, 0.5])
    return ClassroomRoom(ArrayConfig(), rt60_s=float(rng.uniform(0.3, 0.9)), dims=d, center=c)


def _place(room, rng, lo, hi, dist=(1.2, 5.0)):
    while True:
        az, r = rng.uniform(lo, hi), rng.uniform(*dist)
        p = room.position(az, r)
        if 0.3 < p[0] < room.dims[0] - 0.3 and 0.3 < p[1] < room.dims[1] - 0.3:
            return float(az), float(r)


def _noise(room, rng, length):
    return Placement(fan_noise(int(length * 16000) + 10, 16000, rng), float(rng.choice([-85, 85])), 2.8)


def make_scene(args) -> dict:
    kind, level, i, seed, dims, center = args
    rng = np.random.default_rng([seed, i, list(LEVELS).index(level), kind == "two"])
    room = _room(rng, level, dims, center)
    pre = 0.6
    if kind == "one":
        a = synth_speech(SENTENCES[i % 8], VOICES[i % 4])
        az, r = _place(room, rng, -78, 78)
        length = len(a) / 16000 + pre + 0.5
        tg, nz = room.render_each([Placement(a, az, r, pre), _noise(room, rng, length)], length)
        x = tg + scale_to_snr(tg, nz, rng.uniform(5, 15)) + 0.002 * rng.standard_normal(tg.shape)
        return {"kind": kind, "level": level, "x": x.astype(np.float32), "az": [az], "pre": pre, "rt60": room.rt60_s}
    a = synth_speech(SENTENCES[i % 8], VOICES[i % 4])
    b = synth_speech(SENTENCES[(i + 3) % 8], VOICES[(i + 1) % 4])
    (az1, r1), (az2, r2) = _place(room, rng, -75, -8), _place(room, rng, 8, 75)
    offset = len(a) / 16000 * 0.5
    length = max(len(a) / 16000, offset + len(b) / 16000) + pre + 0.5
    i1, i2, nz = room.render_each([Placement(a, az1, r1, pre), Placement(b, az2, r2, pre + offset), _noise(room, rng, length)], length)
    x = i1 + i2 + scale_to_snr(i1 + i2, nz, rng.uniform(5, 15)) + 0.002 * rng.standard_normal(i1.shape)
    return {"kind": kind, "level": level, "x": x.astype(np.float32), "az": [az1, az2], "pre": pre, "rt60": room.rt60_s}


def _prep(x, pre_s, cfg):
    pre = int(pre_s * cfg.sample_rate)
    q = to_stft(x[:, :pre], cfg)
    return to_stft(x, cfg), quiet_cross_spectrum(q, 100), np.mean(np.abs(q) ** 2, axis=2)


# ---------- 1. 孪生标定 ----------
def calibrate(n: int = 240, seed: int = 1, dims=NOMINAL_DIMS, center=NOMINAL_CENTER, procs: int = 4) -> DewarpCurve:
    """数字孪生：按标称尺寸（含 mild 级测量误差抖动、RT60 0.3–0.9 s 抖动）仿真虚拟发言，拟合反畸变曲线。"""
    cfg = ArrayConfig()
    with Pool(procs) as p:
        scenes = p.map(make_scene, [("one", "mild", i, seed, dims, center) for i in range(n)])
    meas, true = [], []
    for s in scenes:
        spec, nc, npsd = _prep(s["x"], s["pre"], cfg)
        r = localize(spec, cfg, nc, 1, noise_psd=npsd, dewarp=IDENTITY)
        if r.azimuths:
            meas.append(r.azimuths[0])
            true.append(s["az"][0])
    return DewarpCurve.fit(np.asarray(meas), np.asarray(true))


# ---------- 2. 定位 ----------
def bench_localization(scenes: int, seed: int, procs: int = 4) -> dict:
    cfg = ArrayConfig()
    jobs = [(k, lv, i, seed, NOMINAL_DIMS, NOMINAL_CENTER) for k in ("one", "two") for lv in LEVELS for i in range(scenes)]
    with Pool(procs) as p:
        data = p.map(make_scene, jobs)
    methods = {
        "SRP-PHAT 噪声指纹（基准）": lambda sp, nc, ps, k: estimate_sources(sp, cfg, max_sources=k, noise_cross=nc),
        "起音+扩散补偿（消融：无孪生）": lambda sp, nc, ps, k: localize(sp, cfg, nc, k, noise_psd=ps, dewarp=IDENTITY).azimuths,
        "起音+扩散补偿+孪生反畸变（团队方案）": lambda sp, nc, ps, k: localize(sp, cfg, nc, k, noise_psd=ps).azimuths,
    }
    err: dict = {}
    miss: dict = {}
    for s in data:
        spec, nc, npsd = _prep(s["x"], s["pre"], cfg)
        t = sorted(s["az"])
        for name, fn in methods.items():
            est = sorted(fn(spec, nc, npsd, len(t)))
            key = (s["kind"], s["level"], name)
            if len(est) < len(t):
                miss[key] = miss.get(key, 0) + 1
                e = [90.0] * len(t)
            else:
                e = [abs(a - b) for a, b in zip(est, t)]
            err.setdefault(key, []).extend(e)
            err.setdefault((s["kind"], "all", name), []).extend(e)
    out: dict = {}
    for (kind, level, name), v in err.items():
        out.setdefault("单人" if kind == "one" else "双人重叠", {}).setdefault(level, {})[name] = summarize(v) | {
            "missed_scenes": miss.get((kind, level, name), 0) if level != "all" else sum(
                m for (k2, l2, n2), m in miss.items() if k2 == kind and n2 == name)}
    return out


def bench_official_scenes(scenes: int, seed: int = 2026) -> dict:
    """与 scripts/benchmark.py 分离场景同分布的独立抽样，只比较方位误差。
    （benchmark.py 的随机序列先被去噪实验消耗，与样本长度相关，这里不逐位复刻。）"""
    cfg, room = ArrayConfig(), ClassroomRoom(ArrayConfig())
    rng = np.random.default_rng(seed + 1)
    res: dict = {"baseline": [], "ours": []}
    found = {"baseline": 0, "ours": 0}
    for i in range(scenes):
        a = synth_speech(SENTENCES[i % 8], VOICES[i % 4])
        b = synth_speech(SENTENCES[(i + 3) % 8], VOICES[(i + 1) % 4])
        az1, az2 = rng.uniform(-70, -10), rng.uniform(10, 70)
        offset = len(a) / 16000 * 0.5
        length = max(len(a) / 16000, offset + len(b) / 16000) + 1.0
        pre = 0.6
        i1, i2, nz = room.render_each([Placement(a, az1, 2.5, pre), Placement(b, az2, 2.5, pre + offset),
                                       Placement(fan_noise(int(length * 16000) + 10, 16000, rng), float(rng.choice([-85, 85])), 3.5)], length)
        x = i1 + i2 + scale_to_snr(i1 + i2, nz, 15)
        spec, nc, npsd = _prep(x, pre, cfg)
        for name, est in (("baseline", estimate_sources(spec, cfg, max_sources=2, noise_cross=nc)),
                          ("ours", localize(spec, cfg, nc, 2, noise_psd=npsd).azimuths)):
            est = sorted(est)
            if len(est) < 2:
                res[name] += [90.0, 90.0]
                continue
            found[name] += 1
            res[name] += [abs(est[0] - az1), abs(est[1] - az2)]
    return {"setup": "与 scripts/benchmark.py 分离场景同分布：RT60 0.45 s、两人各距 2.5 m、方位 ±10–70°、SNR 15 dB，漏检计 90°",
            "基准": summarize(res["baseline"]) | {"two_found": f"{found['baseline']}/{scenes}"},
            "团队方案": summarize(res["ours"]) | {"two_found": f"{found['ours']}/{scenes}"}}


# ---------- 3. 跟踪 ----------
STUDENT_VOICES = ["cmn", "cmn+f2", "cmn+m2", "cmn+f4", "cmn+m4", "cmn+f1", "cmn+m6"]


def make_lesson(args) -> dict:
    """一节课 14 句：5 名学生，其中两人前后排同方向（方位差 < 4°）；第 9 句起一名学生换到对侧，并在第 9、12 句发言。"""
    i, seed = args
    rng = np.random.default_rng([seed, 77, i])
    room = _room(rng, "mild")
    voices = rng.choice(len(STUDENT_VOICES), 5, replace=False)
    students = []
    for k in range(5):
        lo, hi = (-70, -10) if k % 2 == 0 else (10, 70)
        az, r = _place(room, rng, lo, hi, (1.5, 2.6))
        students.append({"az": az, "r": r, "voice": {"voice": STUDENT_VOICES[voices[k]], "pitch": int(rng.integers(35, 85)),
                                                      "speed": int(rng.integers(140, 175))}})
    # 前后排：学生 1 坐到学生 0 正后方
    students[1]["az"] = students[0]["az"] + float(rng.uniform(-3, 3))
    students[1]["r"] = min(students[0]["r"] + 1.8, 4.6)
    while not (0.3 < room.position(students[1]["az"], students[1]["r"])[0] < room.dims[0] - 0.3
               and room.position(students[1]["az"], students[1]["r"])[1] < room.dims[1] - 0.3):
        students[1]["r"] -= 0.2
    order = [0, 1, 2, 3, 4] + list(rng.integers(0, 5, 9))
    mover = int(rng.integers(0, 5))
    order[8] = order[11] = mover  # 换座后至少说两句
    utts = []
    for j, k in enumerate(order):
        s = students[k]
        if j == 8:  # 换座：mover 换到对侧
            m = students[mover]
            m["az"], m["r"] = _place(room, rng, *((10, 70) if m["az"] < 0 else (-70, -10)), (1.5, 3.0))
        sp = synth_speech(SENTENCES[int(rng.integers(len(SENTENCES)))], s["voice"])
        length = len(sp) / 16000 + 1.0
        tg, nz = room.render_each([Placement(sp, s["az"], s["r"], 0.6), _noise(room, rng, length)], length)
        x = tg + scale_to_snr(tg, nz, rng.uniform(8, 15)) + 0.002 * rng.standard_normal(tg.shape)
        utts.append({"speaker": int(k), "az": s["az"], "x": x.astype(np.float32), "moved": j >= 8 and k == mover,
                     "front_back": k in (0, 1)})
    return {"utts": utts, "mover": mover}


def _purity_coverage(truth: list[int], labels: list[str]) -> tuple[float, float]:
    t, lab = np.asarray(truth), np.asarray(labels)
    pur = sum(np.bincount(t[lab == l]).max() for l in set(labels)) / len(t)
    cov = sum(np.unique(lab[t == s], return_counts=True)[1].max() for s in set(truth)) / len(t)
    return float(pur), float(cov)


def bench_tracking(lessons: int, seed: int, procs: int = 4) -> dict:
    cfg = ArrayConfig()
    with Pool(procs) as p:
        data = p.map(make_lesson, [(i, seed) for i in range(lessons)])
    combos = {
        "方位就近归并（基准）": ("base_az", "base_trk"),
        "联合跟踪 + 基准方位（消融）": ("base_az", "joint"),
        "方位就近归并 + 新定位（消融）": ("our_az", "base_trk"),
        "方位×声纹联合跟踪 + 新定位（团队方案）": ("our_az", "joint"),
    }
    stats: dict = {k: {"purity": [], "coverage": [], "f1": [], "front_back_split": [], "mover_kept": [], "mover_flagged": []} for k in combos}
    for lesson in data:
        feats = []
        for u in lesson["utts"]:
            spec, nc, npsd = _prep(u["x"], 0.6, cfg)
            b = estimate_sources(spec, cfg, max_sources=1, noise_cross=nc)
            r = localize(spec, cfg, nc, 1, noise_psd=npsd)
            feats.append({"base_az": b[0] if b else 0.0, "our_az": r.azimuths[0] if r.azimuths else 0.0,
                          "conf": r.confidence[0] if r.confidence else 0.0, "audio": u["x"][0, 9600:]})
        truth = [u["speaker"] for u in lesson["utts"]]
        for name, (az_key, trk) in combos.items():
            tracker = SpeakerTracker() if trk == "joint" else BaselineTracker()
            labels, hints = [], []
            for j, f in enumerate(feats):
                if trk == "joint":
                    d = tracker.assign(f[az_key], j * 5000, j * 5000 + 3000, f["audio"], 16000, f["conf"] if az_key == "our_az" else None)
                    labels.append(d.label)
                    hints.append(d.diagnostics.get("possible_rebind_of"))
                else:
                    d = tracker.assign(f[az_key], j * 5000)
                    labels.append(d.label)
                    hints.append(None)
            pur, cov = _purity_coverage(truth, labels)
            st = stats[name]
            st["purity"].append(pur)
            st["coverage"].append(cov)
            st["f1"].append(2 * pur * cov / (pur + cov))
            fb = [labels[j] for j, u in enumerate(lesson["utts"]) if u["front_back"]]
            fb_truth = [truth[j] for j, u in enumerate(lesson["utts"]) if u["front_back"]]
            # 前后排两人是否被分成不同标签：两人各自的多数标签不同
            maj = {s: max(set(l for l, t in zip(fb, fb_truth) if t == s), key=fb.count) for s in set(fb_truth)}
            st["front_back_split"].append(float(len(set(maj.values())) == len(maj)))
            m = lesson["mover"]
            before = [labels[j] for j, u in enumerate(lesson["utts"]) if u["speaker"] == m and not u["moved"]]
            after = [labels[j] for j, u in enumerate(lesson["utts"]) if u["moved"]]
            if before and after:
                own = max(set(before), key=before.count)
                st["mover_kept"].append(float(own in after))
                first = next(j for j, u in enumerate(lesson["utts"]) if u["moved"])
                # 换座后第一句：直接沿用原标签，或给出“可能是换座的原标签”提示，都算认出
                st["mover_flagged"].append(float(labels[first] == own or hints[first] == own))
    out = {}
    for name, st in stats.items():
        out[name] = {"purity": summarize(st["purity"]), "coverage": summarize(st["coverage"]), "f1": summarize(st["f1"]),
                     "前后排被正确分开": f"{int(sum(st['front_back_split']))}/{len(st['front_back_split'])}",
                     "换座后沿用原标签": f"{int(sum(st['mover_kept']))}/{len(st['mover_kept'])}",
                     "换座后第一句被认出（沿用或提示）": f"{int(sum(st['mover_flagged']))}/{len(st['mover_flagged'])}"}
    return out


def run(scenes: int = 12, seed: int = 2026) -> dict:
    t0 = time.time()
    res = {
        "data_origin": "simulated",
        "setup": {"room": "标称 8×6×3 m，RT60 随机 0.3–0.9 s（镜像法）；真实尺寸与阵列位置按 exact/mild/harsh 偏离标称",
                  "mics": "2 支，间距 0.08 m", "speech": "espeak-ng 中文合成语音", "noise": "风扇/投影仪点源，SNR 5–15 dB",
                  "seed": seed, "dewarp_curve": "调参种子 1 生成，评测种子与之不同"},
        "localization": bench_localization(scenes, seed),
        "official_like": bench_official_scenes(scenes, seed),
        "tracking": bench_tracking(max(scenes // 2, 4), seed),
    }
    res["elapsed_s"] = round(time.time() - t0, 1)
    return res


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "calibrate":
        ap = argparse.ArgumentParser()
        ap.add_argument("cmd")
        ap.add_argument("--dims", default="8,6,3")
        ap.add_argument("--center", default="4,1,1.2")
        ap.add_argument("--n", type=int, default=240)
        a = ap.parse_args()
        curve = calibrate(a.n, 1, tuple(map(float, a.dims.split(","))), tuple(map(float, a.center.split(","))))
        print(json.dumps({"measured": curve.measured, "true": curve.true}))
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--scenes", type=int, default=12)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    res = run(args.scenes, args.seed)
    (args.out / "bench_localization.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
