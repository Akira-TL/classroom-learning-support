"""系统级端到端评测：合成整段“课堂对话”按 100 ms 帧流式推进 Session，对照剧本给整条流水线打分。

和 benchmark.py 的区别：benchmark 单独考核每个算法；这里考核拼起来以后，应用侧真正拿到的事件对不对。

每个场景 6–8 句，3–4 名学生 + 教师，含抢话重叠、邻座同方向不同人、换座。指标：
- line_recall      剧本句子被某个转写事件覆盖（时间重叠 ≥ 50%）的比例
- azimuth_mae_deg  命中句的方位误差
- speaker_purity / speaker_coverage   匿名标签与真实说话人的一致度（纯度：同一标签里多数是同一人；覆盖：同一人多数用同一标签）
- segment_si_sdr_db 命中句输出音频（处理音轨或原音频）相对该说话人干净混响语音的 SI-SDR
- enrolled_id_acc  有课前声纹注册时，命中句的注册匹配与真实说话人一致的比例（仅 *_enrolled）
- overlap_f1       真实重叠句是否被标 overlap.present
- contract_ok      sequence 连续、session.ended 收尾、无 ASR 时不伪造 text

用法：uv run python scripts/e2e_eval.py 输出目录 [--scenes 6] [--profiles baseline,integrated,...]
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import soundfile as sf

from classroom_speech.events import EventType
from classroom_speech.pipeline import Session
from classroom_speech.sim import SENTENCES, VOICES, ClassroomRoom, Placement, fan_noise, scale_to_snr, synth_speech
from classroom_speech.stages import Profile

SEED = 2026
TEACHER = {"voice": "cmn+m3", "pitch": 35, "speed": 175}
QUESTIONS = ["每块是四分之一吗？", "这样分是平均分吗？", "谁来说说为什么？"]


def make_lesson(room: ClassroomRoom, rng: np.random.Generator, snr_db: float = 5.0):
    """一节小片段：教师提问 → 学生轮流回答，夹一次抢话、一次邻座、一次换座。"""
    n_students = int(rng.integers(3, 5))
    seats = sorted(rng.choice(np.arange(-70, 71, 5), n_students, replace=False).astype(float))
    neighbour = seats[0] + float(rng.choice([-1, 1])) * rng.uniform(6, 10)  # 与学生 0 几乎同方向的另一名学生
    students = [{"name": f"学生{k}", "az": az, "voice": VOICES[k % len(VOICES)] | {"pitch": 25 + 17 * k}, "dist": rng.uniform(1.8, 3.5)} for k, az in enumerate(seats)]
    students.append({"name": "邻座", "az": float(np.clip(neighbour, -80, 80)), "voice": VOICES[(n_students + 1) % len(VOICES)] | {"pitch": 95},
                     "dist": rng.uniform(1.8, 3.5)})
    lines = [("教师", 0.0, 1.2, TEACHER, QUESTIONS[int(rng.integers(len(QUESTIONS)))], 0.6)]
    order = list(rng.permutation(len(students)))
    for j, k in enumerate(order):
        s = students[k]
        gap = -float(rng.uniform(1.0, 1.8)) if j == 1 else float(rng.uniform(0.7, 1.2))  # 第二个回答抢话
        lines.append((s["name"], s["az"], s["dist"], s["voice"], SENTENCES[int(rng.integers(len(SENTENCES)))], gap))
    # 换座：第一个回答的学生换到对面再说一句（应被识别为同一人或给出 rebind 提示）
    mover = students[order[0]]
    lines.append((mover["name"], float(np.clip(-mover["az"] + rng.uniform(-10, 10), -80, 80)), mover["dist"], mover["voice"],
                  SENTENCES[int(rng.integers(len(SENTENCES)))], 1.0))
    placements, meta, prev_end = [], [], 0.6
    for who, az, dist, voice, text, gap in lines:
        sp = synth_speech(text, voice)
        t0 = max(prev_end + gap, 0.6)
        placements.append(Placement(sp, az, dist, t0))
        meta.append({"speaker": who, "azimuth_deg": az, "start_s": t0, "end_s": t0 + len(sp) / 16000, "text": text})
        prev_end = max(prev_end, t0 + len(sp) / 16000)
    length = prev_end + 1.0
    images = room.render_each(placements, length)
    speech = sum(images)
    (fan,) = room.render_each([Placement(fan_noise(int(length * 16000) + 10, 16000, rng), float(rng.choice([-80, 80])), 3.5)], length)
    mix = speech + scale_to_snr(speech, fan, snr_db) + 0.002 * rng.standard_normal(speech.shape)
    mix = mix / (np.max(np.abs(mix)) / 0.9)
    for i, m in enumerate(meta):
        m["overlaps"] = any(i != j and m["start_s"] < o["end_s"] and o["start_s"] < m["end_s"] for j, o in enumerate(meta))
    gain = 1 / (np.max(np.abs(speech + scale_to_snr(speech, fan, snr_db))) / 0.9)  # 与 mix 同一缩放（白噪声影响可忽略）
    for m, img in zip(meta, images):
        m["_ref"] = (img[0] * gain).astype(np.float32)
    # 课前注册用的说话人档案：原座位、音色（换座的学生按原座位注册）
    people = {"教师": (TEACHER, 0.0, 1.2)} | {st["name"]: (st["voice"], st["az"], st["dist"]) for st in students}
    return mix.astype(np.float32), meta, people


ENROLL_TEXTS = ["我们今天学习分数。", "老师，我想回答这个问题。"]  # 与测试台词不同


def make_enrollment(room: ClassroomRoom, people: dict, rng: np.random.Generator) -> dict:
    """每人在自己座位上读两句注册语，得到双通道注册音频 {label: (2, N)}。"""
    out = {}
    for name, (voice, az, dist) in people.items():
        sp = np.concatenate([synth_speech(t, voice) for t in ENROLL_TEXTS])
        (img,) = room.render_each([Placement(sp, az, dist, 0.3)], len(sp) / 16000 + 0.8)
        out[name] = (img + 0.002 * rng.standard_normal(img.shape)).astype(np.float32)
    return out


def run_session(x: np.ndarray, profile: Profile, out_dir: Path, context: dict | None = None,
                enrollment: dict | None = None) -> tuple[list, dict]:
    s = Session(f"ses_{int(time.time() * 1e3) % 10**8}", out_dir, asr=None, data_origin="simulated", profile=profile, context=context,
                enrollment=enrollment)
    frame = 1600
    for i in range(0, x.shape[1], frame):
        s.push(x[:, i : i + frame])
    s.end()
    return s.events, s.stages.origin


def segments_from_events(events) -> list[dict]:
    segs: dict[str, dict] = {}
    for e in events:
        if e.segment_id is None:
            continue
        d = segs.setdefault(e.segment_id, {"id": e.segment_id})
        if e.event_type == EventType.SOURCE_POSITION:
            for r in e.sources:
                d["azimuth" if r.kind == "azimuth" else "label"] = r.value
                d["rebind"] = d.get("rebind", False) or r.rebind_hint
            d["enrolled"] = (e.diagnostics or {}).get("enrolled_match")
            d["start_ms"], d["end_ms"] = e.start_ms, e.end_ms
        elif e.event_type == EventType.TRANSCRIPT_FINAL:
            d["overlap"] = bool(e.overlap and e.overlap.present)
            d["text"] = e.text
            d["reliability"] = e.reliability_state.value if e.reliability_state else None
    return list(segs.values())


def si_sdr(ref: np.ndarray, est: np.ndarray) -> float:
    n = min(len(ref), len(est))
    ref, est = ref[:n] - ref[:n].mean(), est[:n] - est[:n].mean()
    s = (est @ ref) / (ref @ ref + 1e-12) * ref
    return float(10 * np.log10(np.sum(s**2) / (np.sum((est - s) ** 2) + 1e-12)))


def segment_audio(archive: Path, sg: dict, mix: np.ndarray) -> np.ndarray:
    """应用侧拿到的这一段音频：处理音轨存在就用处理音轨，否则是原音频 mic0。"""
    for kind in ("separated", "denoised"):
        f = archive / f"{sg['id']}_{kind}.wav"
        if f.exists():
            return sf.read(f, dtype="float32")[0]
    a, b = int(sg["start_ms"] * 16), int(sg["end_ms"] * 16)
    return mix[0, a:b]


def score(meta, segs, events, archive: Path | None = None, mix: np.ndarray | None = None) -> dict:
    matched = []
    for line in meta:
        a, b = line["start_s"] * 1000, line["end_s"] * 1000
        best, best_score = None, 0.0
        for sg in segs:
            ov = max(0.0, min(b, sg["end_ms"]) - max(a, sg["start_ms"]))
            if ov <= 0:
                continue
            # 时间重叠为主，方位接近为辅：重叠句里两个分离片段时间相近，用方位区分
            sc = ov / (b - a) - abs(sg["azimuth"] - line["azimuth_deg"]) / 180
            if sc > best_score:
                best, best_score = sg, sc
        covered = best is not None and max(0.0, min(b, best["end_ms"]) - max(a, best["start_ms"])) / (b - a) >= 0.5
        matched.append(best if covered else None)
    hits = [(m, s) for m, s in zip(meta, matched) if s is not None]
    # 音质：命中句的输出音频 vs 该说话人在 mic0 上的混响语音（同一时间窗）
    sdr = []
    if archive is not None:
        for m, sg in hits:
            a, b = int(sg["start_ms"] * 16), int(sg["end_ms"] * 16)
            sdr.append(si_sdr(m["_ref"][a:b], segment_audio(archive, sg, mix)))
    az_err = [abs(s["azimuth"] - m["azimuth_deg"]) for m, s in hits]
    # 说话人一致性：纯度与覆盖（换座句子也按真实身份算）
    by_label: dict[str, list[str]] = {}
    by_spk: dict[str, list[str]] = {}
    for m, s in hits:
        by_label.setdefault(s["label"], []).append(m["speaker"])
        by_spk.setdefault(m["speaker"], []).append(s["label"])
    enrolled = [s.get("enrolled") for _, s in hits]
    enroll_acc = (sum(s.get("enrolled") == m["speaker"] for m, s in hits) / len(hits)) if any(enrolled) else None
    purity = sum(max(v.count(x) for x in set(v)) for v in by_label.values()) / max(len(hits), 1)
    coverage = sum(max(v.count(x) for x in set(v)) for v in by_spk.values()) / max(len(hits), 1)
    tp = sum(1 for m, s in hits if m["overlaps"] and s.get("overlap"))
    fp = sum(1 for m, s in hits if not m["overlaps"] and s.get("overlap"))
    fn = sum(1 for m, s in zip(meta, matched) if m["overlaps"] and not (s and s.get("overlap")))
    f1 = 2 * tp / max(2 * tp + fp + fn, 1)
    seqs = [e.sequence for e in events]
    contract_ok = (seqs == list(range(1, len(seqs) + 1)) and events[-1].event_type == EventType.SESSION_ENDED
                   and all(e.text is None for e in events if e.event_type == EventType.TRANSCRIPT_FINAL and e.status == "asr_unavailable"))
    return {
        "lines": len(meta), "segments": len(segs), "line_recall": len(hits) / len(meta),
        "azimuth_mae_deg": float(np.mean(az_err)) if az_err else None,
        "segment_si_sdr_db": float(np.mean(sdr)) if sdr else None, "enrolled_id_acc": enroll_acc, "speaker_purity": purity, "speaker_coverage": coverage, "overlap_f1": f1, "contract_ok": contract_ok,
    }


def summarize(values) -> dict:
    v = np.asarray([x for x in values if x is not None], dtype=float)
    if len(v) == 0:
        return {"mean": None, "n": 0}
    ci = 1.96 * v.std(ddof=1) / np.sqrt(len(v)) if len(v) > 1 else 0.0
    return {"mean": round(float(v.mean()), 3), "ci95": round(float(ci), 3), "n": len(v)}


PROFILES = {
    "baseline": Profile.baseline(),
    "integrated": Profile(),
    "only_localization": replace(Profile.baseline(), localization=True, tracking=True),
    "only_denoise": replace(Profile.baseline(), denoise=True),
    "only_separation": replace(Profile.baseline(), separation=True),
    "only_math_guard": replace(Profile.baseline(), math_guard=True),
    "integrated_no_refine": Profile(refine_single=False),  # 消融：去掉整合层的单人区间改走去噪
    "integrated_enrolled": Profile(),  # 同 integrated，另加课前声纹注册
    "integrated_enrolled_no_refine": Profile(refine_single=False),  # 消融：注册分路后单人区间仍用分离掩码
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--scenes", type=int, default=6)
    ap.add_argument("--profiles", default="baseline,integrated")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    room = ClassroomRoom()
    rng = np.random.default_rng(SEED)
    t0 = time.time()
    lessons = [make_lesson(room, rng) for _ in range(args.scenes)]
    enroll_rng = np.random.default_rng(SEED + 1)
    enrollments = [make_enrollment(room, people, enroll_rng) for _, _, people in lessons] if "enrolled" in args.profiles else None
    result: dict = {"data_origin": "simulated", "seed": SEED, "scenes": args.scenes,
                    "setup": "8×6×3 m 教室 RT60 0.45 s，5 dB 风扇噪声；每场 3–4 名学生 + 邻座同方向 + 教师，含一次抢话与一次换座",
                    "profiles": {}}
    for name in args.profiles.split(","):
        rows, origin = [], None
        for li, (x, meta, _) in enumerate(lessons):
            enr = enrollments[li] if "enrolled" in name else None
            with tempfile.TemporaryDirectory() as tmp:
                events, origin = run_session(x, PROFILES[name], Path(tmp), enrollment=enr)
                rows.append(score(meta, segments_from_events(events), events, Path(tmp), x))
        keys = [k for k in rows[0] if k not in ("lines", "segments", "contract_ok")]
        result["profiles"][name] = {
            "stage_origin": origin,
            **{k: summarize([r[k] for r in rows]) for k in keys},
            "contract_ok": f"{sum(r['contract_ok'] for r in rows)}/{len(rows)}",
        }
    result["elapsed_s"] = round(time.time() - t0, 1)
    (args.out / "e2e.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
