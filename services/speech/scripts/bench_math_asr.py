"""方向四评测：数学语义守卫 vs 通用 ASR / 静态热词 / 朴素题目热词。

两种模式：
  离线（默认，云端可跑）：逐音节拼音合成课堂句子（espeak-ng，字级时间戳精确已知）+ 教室混响与风扇噪声，
      识别器用 SimulatedConfusionAsr 行为模型（模拟热词偏置），声调—声母仲裁跑在真实合成波形上。
      结果只说明决策逻辑，data_origin=simulated。
  实测（--engine funasr，在 RTX 2060 上）：同一批句子换成 FunASR SeACo-Paraformer 真实解码；
      可加 --manifest 用真人录音；加 --overlap 比较重叠段分离前后的转写。

指标（按语义槽统计，一个分数 / 一个“平均分”算一个槽）：
  关键表达准确率   输出里该槽的取值和否定极性都对
  沉默错误率       槽错了、却没被标“待核验”——会被直接当成学生证据的错误，越低越好
  错答被静默纠正率 学生真说错了，输出却变成题目期望的答案，且没标待核验
  待核验率         老师需要回听的槽占比（人工成本）

用法：uv run python scripts/bench_math_asr.py 输出目录 [--scenes 4] [--engine sim|funasr] [--overlap] [--manifest m.jsonl]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

try:
    from classroom_speech.math_asr import (
        CONFUSABLE, STATIC_HOTWORDS, GuardConfig, MathGuardedAsr, SimulatedConfusionAsr, _decode, _isolated_numerals,
        arbitrate, context_hotwords_naive, context_numbers, extract_claims, symmetric_hotwords,
    )
except ImportError:  # 在 contrib 目录里直接跑
    from math_asr import (  # type: ignore
        CONFUSABLE, STATIC_HOTWORDS, GuardConfig, MathGuardedAsr, SimulatedConfusionAsr, _decode, _isolated_numerals,
        arbitrate, context_hotwords_naive, context_numbers, extract_claims, symmetric_hotwords,
    )

SR = 16000
SEED = 2026

# (题目, 学生实际说的话, 是否与题目期望不一致——学生真实错答)
ITEMS = [
    ("把一张纸平均分成4份，每份是它的几分之几？", "每份是它的四分之一。", False),
    ("把一张纸平均分成4份，每份是它的几分之几？", "每份是它的十分之一。", True),
    ("把一张纸平均分成4份，每份是它的几分之几？", "有四块就是四分之一。", False),
    ("把一张纸平均分成4份，每份是它的几分之几？", "这个图形没有平均分，不能说是四分之一。", False),
    ("把一根绳子平均分成10段，每段是全长的几分之几？", "每段是全长的十分之一。", False),
    ("把一根绳子平均分成10段，每段是全长的几分之几？", "我觉得是四分之一。", True),
    ("这样分是平均分吗？", "这样分没有平均分。", False),
    ("这样分是平均分吗？", "这样分是平均分。", False),
    ("这两块一样大吗？", "这两块不一样大。", False),
    ("这两块一样大吗？", "这两块一样大。", False),
    ("七分之一和二分之一哪个大？", "七分之一比二分之一小。", False),
    ("七分之一和二分之一哪个大？", "我觉得一分之七比二分之一大。", True),
]

PINYIN = dict(p.split(":") for p in (
    "一:yi1 七:qi1 不:bu4 两:liang3 个:ge4 之:zhi1 二:er4 份:fen4 全:quan2 分:fen1 十:shi2 四:si4 图:tu2 均:jun1 块:kuai4 "
    "大:da4 它:ta1 小:xiao3 就:jiu4 平:ping2 形:xing2 得:de2 我:wo3 是:shi4 有:you3 样:yang4 段:duan4 每:mei3 比:bi3 "
    "没:mei2 的:de5 能:neng2 觉:jue2 说:shuo1 这:zhe4 长:chang2"
).split())

VOICES = [{"pitch": 45, "speed": 165}, {"pitch": 70, "speed": 175}, {"pitch": 90, "speed": 185}, {"pitch": 60, "speed": 155}]
SNRS = (20, 10, 5, 0)


# ---------------- 合成 ----------------

def _espeak_syllable(py: str, voice: dict, cache: dict) -> np.ndarray:
    key = (py, voice["pitch"], voice["speed"])
    if key not in cache:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "s.wav"
            subprocess.run(["espeak-ng", "-v", "cmn-latn-pinyin", "-p", str(voice["pitch"]), "-s", str(voice["speed"]),
                            "-w", str(out), py.replace("5", "")], check=True, capture_output=True)
            a, sr = sf.read(out, dtype="float32")
        g = np.gcd(sr, SR)
        a = resample_poly(a, SR // g, sr // g).astype(np.float32)
        idx = np.flatnonzero(np.abs(a) > 0.01 * np.abs(a).max())
        cache[key] = a[max(idx[0] - 80, 0) : idx[-1] + 80] if len(idx) else a
    return cache[key]


def synth_sentence(text: str, voice: dict, cache: dict) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """逐字合成并拼接，返回音频与每个非标点字的 [起, 止] 毫秒——相当于完美的字级时间戳。"""
    parts, times, t = [np.zeros(int(0.3 * SR), np.float32)], [], int(0.3 * SR)
    for ch in text:
        if ch not in PINYIN:
            parts.append(np.zeros(int(0.15 * SR), np.float32))
            t += int(0.15 * SR)
            continue
        s = _espeak_syllable(PINYIN[ch], voice, cache)
        times.append((t * 1000 // SR, (t + len(s)) * 1000 // SR))
        parts += [s, np.zeros(int(0.02 * SR), np.float32)]
        t += len(s) + int(0.02 * SR)
    parts.append(np.zeros(int(0.3 * SR), np.float32))
    x = np.concatenate(parts)
    return x / (np.abs(x).max() + 1e-9) * 0.5, times


def classroom(x: np.ndarray, snr_db: float, rng: np.random.Generator, room=None, azimuth: float = 20.0) -> np.ndarray:
    """教室混响 + 风扇噪声后的 mic0 信号。"""
    from classroom_speech.sim import Placement, fan_noise

    n = len(x)
    if room is not None:
        tgt, nz = room.render_each([Placement(x, azimuth, 2.0, 0.0), Placement(fan_noise(n + 10, SR, rng), -60.0, 3.5)], (n + 1) / SR)
        s, v = tgt[0, :n], nz[0, :n]
    else:
        s, v = x, fan_noise(n, SR, rng)
    v = v * np.sqrt(np.mean(s**2) / (np.mean(v**2) * 10 ** (snr_db / 10) + 1e-12))
    return (s + v + 0.002 * rng.standard_normal(n)).astype(np.float32)


# ---------------- 打分 ----------------

def ref_slots(text: str) -> list:
    return [c for c in extract_claims(text) if c.kind != "comparison"]


def _edit(a: str, b: str) -> int:
    a, b = [c for c in a if c not in "，。？！"], [c for c in b if c not in "，。？！"]
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(b) + 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
    return d[-1]


def _rate(k: int, n: int) -> dict:
    p = k / n if n else 0.0
    return {"rate": round(p, 3), "ci95": round(1.96 * np.sqrt(p * (1 - p) / n), 3) if n else None, "k": int(k), "n": int(n)}


# ---------------- 数据 ----------------

MARGIN_MU = {20: 2.2, 10: 1.4, 5: 0.9, 0: 0.4}  # 行为模型：信噪比越低，易混位置的声学裕度越小


def build_items(scenes: int, seed: int, reverb: bool = True) -> list[dict]:
    from classroom_speech.sim import ClassroomRoom

    rng = np.random.default_rng(seed)
    room = ClassroomRoom() if reverb else None
    cache: dict = {}
    data = []
    for sc in range(scenes):
        voice = VOICES[sc % len(VOICES)]
        for snr in SNRS:
            for q, ref, wrong in ITEMS:
                clean, times = synth_sentence(ref, voice, cache)
                x = classroom(clean, snr, rng, room, azimuth=float(rng.uniform(-60, 60)))
                margins = {p: float(rng.normal(MARGIN_MU[snr], 1.0)) for p in critical_positions(ref)}
                data.append({"question": q, "ref": ref, "student_error": wrong, "snr": snr, "voice": sc % len(VOICES),
                             "audio": x, "times": times, "margins": margins,
                             "expected_dens": context_numbers(q)})
    return data


def critical_positions(text: str) -> list[int]:
    """模拟识别器的易混位置：分数 / 分成 N 份里的单字数，以及否定词。"""
    pos = []
    for c in ref_slots(text):
        if c.kind in ("fraction", "partition"):
            pos += [c.span[0] + i for i, _ in _isolated_numerals(c.surface)]
        if c.negated:
            neg = c.detail.get("negator") or ""
            k = text.rfind(neg, 0, c.span[1])
            pos += [k] if k >= 0 else []
    return sorted(set(pos))


# ---------------- 方法 ----------------

def make_methods(engine_for):
    """engine_for(item) → 底层识别器（模拟或 FunASR）。每个方法返回 (输出原文, 被标待核验的槽原文集合)。"""

    def plain(hot):
        def f(it):
            d = _decode(engine_for(it), it["audio"], SR, hot(it))
            return (d.text if d else ""), set(), {}
        return f

    def guarded(cfg, use_context_for_ranking=True):
        def f(it):
            g = MathGuardedAsr(engine_for(it), cfg)
            if not use_context_for_ranking:  # 热词照常用题目生成，但候选排序不看题目
                r = g.transcribe(it["audio"], SR, context={"question": it["question"], "rank_without_context": True})
            else:
                r = g.transcribe(it["audio"], SR, context={"question": it["question"]})
            if r is None:
                return "", set(), {}
            ranked = {c["slot"]: [a["surface"] for a in c["alternatives"]] for c in r.candidates}
            return r.text, {t["surface"] for t in r.math_terms if t.get("reliability") == "needs_review"}, ranked
        return f

    return {
        "A 通用 ASR（无热词）": plain(lambda it: ""),
        "B 静态数学热词（基准方案）": plain(lambda it: " ".join(STATIC_HOTWORDS)),
        "C 题目热词·朴素（只加期望答案）": plain(lambda it: " ".join(context_hotwords_naive(it["question"]))),
        "C′ 题目热词·对称（不加守卫）": plain(lambda it: " ".join(symmetric_hotwords(it["question"]))),
        "D 数学语义守卫（团队方案）": guarded(GuardConfig()),
        "D− 去掉声调仲裁（消融）": guarded(GuardConfig(phonetic=False)),
        "D− 去掉反事实对质（消融）": guarded(GuardConfig(probe=False)),
        "D− 守卫但用朴素热词（消融）": guarded(GuardConfig(symmetric_hotwords=False)),
        "D− 候选不用题目上下文（消融）": guarded(GuardConfig(), use_context_for_ranking=False),
    }


def evaluate_all(methods, items) -> dict:
    out = {}
    for name, m in methods.items():
        agg = {"slots": 0, "correct": 0, "silent": 0, "flagged": 0, "se_n": 0, "se_erased": 0, "cer_e": 0, "cer_n": 0,
               "wrong_flagged": 0, "top1": 0}
        by_snr: dict[int, dict] = {}
        for it in items:
            text, flagged, ranked = m(it)
            refs, outs = ref_slots(it["ref"]), [c for c in extract_claims(text) if c.kind != "comparison"]
            b = by_snr.setdefault(it["snr"], {"slots": 0, "correct": 0, "silent": 0, "flagged": 0})
            for c in refs:
                same = [o for o in outs if o.kind == c.kind]
                near = min(same, key=lambda o: abs(o.span[0] - c.span[0]), default=None)
                ok = near is not None and near.key == c.key
                is_flag = near is not None and near.surface in flagged
                for acc in (agg, b):
                    acc["slots"] += 1
                    acc["correct"] += ok
                    acc["flagged"] += is_flag
                    acc["silent"] += (not ok) and not is_flag
                if is_flag and not ok:  # 标了待核验的错槽：第一候选是不是学生真说的
                    agg["wrong_flagged"] += 1
                    top = (ranked.get(near.surface) or [None])[0]
                    agg["top1"] += bool(top and any(o.key == c.key for o in extract_claims(top)))
                if it["student_error"] and c.kind == "fraction":
                    agg["se_n"] += 1
                    erased = near is not None and not ok and near.detail.get("den") in it["expected_dens"]
                    agg["se_erased"] += bool(erased and not is_flag)  # 被改成期望答案、且没人会去回听
            agg["cer_e"] += _edit(it["ref"], text)
            agg["cer_n"] += len([ch for ch in it["ref"] if ch not in "，。？！"])
        out[name] = {
            "关键表达准确率": _rate(agg["correct"], agg["slots"]),
            "沉默错误率": _rate(agg["silent"], agg["slots"]),
            "待核验率": _rate(agg["flagged"], agg["slots"]),
            "错答被静默纠正率": _rate(agg["se_erased"], agg["se_n"]),
            "待核验错槽·第一候选即原话": _rate(agg["top1"], agg["wrong_flagged"]),
            "CER": round(agg["cer_e"] / agg["cer_n"], 3),
            "按信噪比": {f"{k} dB": {"关键表达准确率": round(v["correct"] / v["slots"], 3), "沉默错误率": round(v["silent"] / v["slots"], 3),
                                   "待核验率": round(v["flagged"] / v["slots"], 3)} for k, v in sorted(by_snr.items(), key=lambda kv: (isinstance(kv[0], str), -kv[0] if isinstance(kv[0], int) else 0))},
        }
    return out


def phonetic_accuracy(items) -> dict:
    """声调—声母仲裁本身的准确率：在参考字的真实时间段上，判断四/十、一/七。真实合成波形，非行为模型。"""
    res: dict = {}
    for it in items:
        spans = it["times"]
        chars = [i for i, ch in enumerate(it["ref"]) if ch not in "，。？！"]
        idx_of = {ci: k for k, ci in enumerate(chars)}
        for c in ref_slots(it["ref"]):
            if c.kind not in ("fraction", "partition"):
                continue
            for i, ch in _isolated_numerals(c.surface):
                t = spans[idx_of[c.span[0] + i]]
                a, b = max(0, int((t[0] - 60) * SR / 1000)), int((t[1] + 30) * SR / 1000)
                v = arbitrate(it["audio"][a:b], ch, CONFUSABLE[ch][0], SR)
                r = res.setdefault(f"{v.pair} @ {it['snr']} dB", {"n": 0, "correct": 0, "wrong": 0, "abstain": 0})
                r["n"] += 1
                r["correct" if v.favors == ch else "abstain" if v.favors is None else "wrong"] += 1
    for r in res.values():
        r["判对率"] = round(r["correct"] / r["n"], 3)
        r["判错率"] = round(r["wrong"] / r["n"], 3)
    return dict(sorted(res.items()))


def chain_examples(items, engine_for, picks=("每份是它的十分之一。", "这个图形没有平均分，不能说是四分之一。", "这样分没有平均分。", "每份是它的四分之一。")) -> list[dict]:
    """给讲解用的完整链条：参考 → 通用 ASR → 守卫输出（原文 + 槽 + 候选 + 待核验）。"""
    out = []
    for ref in picks:
        cand = [it for it in items if it["ref"] == ref]
        # 优先挑一个通用 ASR 出错或守卫标了待核验的例子，展示链条
        def interesting(it):
            d = _decode(engine_for(it), it["audio"], SR, " ".join(context_hotwords_naive(it["question"])))
            return d is not None and d.text != it["ref"]
        it = next((x for x in cand if interesting(x)), cand[0] if cand else None)
        if it is None:
            continue
        naive = _decode(engine_for(it), it["audio"], SR, " ".join(context_hotwords_naive(it["question"])))
        r = MathGuardedAsr(engine_for(it)).transcribe(it["audio"], SR, context={"question": it["question"]})
        out.append({"题目": it["question"], "学生实际说": ref, "snr_db": it["snr"], "学生真实错答": it["student_error"],
                    "朴素题目热词输出": naive.text if naive else None,
                    "守卫输出原文": r.text if r else None, "reliability": r.reliability if r else None,
                    "review_reasons": r.review_reasons if r else [], "math_terms": r.math_terms if r else [],
                    "candidates": r.candidates if r else []})
    return out


def load_manifest(path: Path) -> list[dict]:
    """真人录音清单（jsonl）：{"audio": "a.wav", "question": "...", "ref": "学生实际说的话", "student_error": false}。
    ref 由人工听写，按“学生实际说的”写，不按正确答案写。"""
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        m = json.loads(line)
        x, sr = sf.read(path.parent / m["audio"], dtype="float32", always_2d=True)
        x = x[:, 0]
        if sr != SR:
            g = np.gcd(sr, SR)
            x = resample_poly(x, SR // g, sr // g).astype(np.float32)
        items.append({"question": m["question"], "ref": m["ref"], "student_error": bool(m.get("student_error")),
                      "snr": m.get("snr_db", "real"), "audio": x, "times": None, "margins": {},
                      "expected_dens": context_numbers(m["question"])})
    return items


def run(scenes: int = 4, seed: int = SEED, engine: str = "sim", reverb: bool = True, manifest: Path | None = None) -> dict:
    if manifest is not None and engine == "sim":
        raise SystemExit("真人录音需要真实识别器：加 --engine funasr")
    items = load_manifest(manifest) if manifest else build_items(scenes, seed, reverb)
    if engine == "funasr":
        from classroom_speech.engines import FunAsrEngine

        base = FunAsrEngine()
        engine_for = lambda it: base  # noqa: E731
        origin = "live_recording+real_asr" if manifest else "simulated_audio+real_asr"
    else:
        engine_for = lambda it: SimulatedConfusionAsr(it["ref"], it["margins"], it["times"])  # noqa: E731
        origin = "simulated"
    return {
        "data_origin": origin,
        "setup": {"speech": "espeak-ng 逐音节拼音合成（cmn-latn-pinyin），字级时间戳精确已知",
                  "room": "8×6×3 m，RT60 0.45 s（镜像法）" if reverb else "无混响",
                  "noise": "风扇/投影仪噪声", "snr_db": list(SNRS), "voices": len(VOICES[: max(1, min(scenes, len(VOICES)))]),
                  "utterances": len(items), "seed": seed,
                  "asr": "SimulatedConfusionAsr 行为模型（热词偏置 bias=1，裕度均值 " + str(MARGIN_MU) + "）" if engine == "sim" else "FunASR paraformer-zh"},
        "methods": evaluate_all(make_methods(engine_for), items),
        "phonetic_arbiter": phonetic_accuracy(items) if not manifest else "真人录音无精确字级时间戳，见各方法结果",
        "examples": chain_examples(items, engine_for),
    }


def run_overlap(scenes: int, seed: int) -> dict:
    """重叠段分离前后转写对比（需 FunASR）：两句同时说，比较直接转写混合 vs 方位锚定分离后各自转写。"""
    from classroom_speech.engines import FunAsrEngine
    from classroom_speech.separation import selective_separate
    from classroom_speech.sim import ClassroomRoom, Placement, fan_noise
    from classroom_speech.spatial import ArrayConfig, estimate_sources, to_stft

    rng, room, cfg, cache = np.random.default_rng(seed), ClassroomRoom(), ArrayConfig(), {}
    asr = MathGuardedAsr(FunAsrEngine())
    rows = []
    for sc in range(scenes):
        for k in range(len(ITEMS)):
            (q1, r1, _), (_q2, r2, _) = ITEMS[k], ITEMS[(k + 5) % len(ITEMS)]
            a, _ = synth_sentence(r1, VOICES[sc % 4], cache)
            b, _ = synth_sentence(r2, VOICES[(sc + 1) % 4], cache)
            n = max(len(a), len(b)) + SR // 2
            az1, az2 = float(rng.uniform(-60, -15)), float(rng.uniform(15, 60))
            s1, s2, nz = room.render_each([Placement(a, az1, 2.0), Placement(b, az2, 2.5, 0.3), Placement(fan_noise(n + 10, SR, rng), -80, 3.5)], n / SR)
            nz = nz * np.sqrt(np.mean(s1[0] ** 2) / (np.mean(nz[0] ** 2) * 10 ** (10 / 10)))
            x = s1 + s2 + nz
            azs = sorted(estimate_sources(to_stft(x, cfg), cfg, max_sources=2))
            mix = asr.transcribe(x[0], SR, context={"question": q1}, overlap=True)
            row = {"refs": [r1, r2], "mixture": mix.text if mix else "", "separated": []}
            if len(azs) >= 2:
                streams, _ = selective_separate(x, azs, cfg)
                for st in streams:
                    g = asr.transcribe(st, SR, context={"question": q1}, overlap=True)
                    row["separated"].append(g.text if g else "")
            rows.append(row)

    def best_slot_acc(ref, hyps):
        ref_keys = {c.key for c in ref_slots(ref)}
        return max((len(ref_keys & {c.key for c in extract_claims(h)}) / max(len(ref_keys), 1) for h in hyps), default=0.0)

    def best_cer(ref, hyps):
        return min((_edit(ref, h) / len(ref) for h in hyps), default=1.0)

    res = {"n_pairs": len(rows), "data_origin": "simulated_audio+real_asr"}
    for key in ("mixture", "separated"):
        hy = lambda r: [r[key]] if key == "mixture" else r[key]  # noqa: E731
        res[key] = {"关键表达准确率": round(float(np.mean([best_slot_acc(ref, hy(r)) for r in rows for ref in r["refs"]])), 3),
                    "CER": round(float(np.mean([best_cer(ref, hy(r)) for r in rows for ref in r["refs"]])), 3)}
    res["rows"] = rows[:6]
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--scenes", type=int, default=4)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--engine", choices=["sim", "funasr"], default="sim")
    ap.add_argument("--no-reverb", action="store_true")
    ap.add_argument("--overlap", action="store_true", help="另跑重叠段分离前后转写对比（需 FunASR）")
    ap.add_argument("--manifest", type=Path, help="真人录音清单 jsonl（需 --engine funasr）")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    res = run(args.scenes, args.seed, args.engine, not args.no_reverb, args.manifest)
    if args.overlap:
        res["overlap"] = run_overlap(max(1, args.scenes // 2), args.seed)
    name = f"math_asr_{args.engine}{'_recorded' if args.manifest else ''}.json"
    (args.out / name).write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    for m, v in res["methods"].items():
        print(f"{m:<26} 第一候选命中 {v['待核验错槽·第一候选即原话']['rate']:.3f}  准确率 {v['关键表达准确率']['rate']:.3f}  沉默错误 {v['沉默错误率']['rate']:.3f}  待核验 {v['待核验率']['rate']:.3f}  错答被静默纠正 {v['错答被静默纠正率']['rate']:.3f}  CER {v['CER']:.3f}")
    print("结果写入", args.out / name)


if __name__ == "__main__":
    main()
