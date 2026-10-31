"""端到端演示：生成“平均分与四分之一”合成课堂片段，分别用基准与整合版流水线流式处理，输出事件流与处理音轨。

转写用测试替身 ScriptByTimeAsr：按时间与方位把剧本台词当作“识别结果”，事件里 engine 如实写为
oracle_script_by_time。它只用来演示数学守卫、重叠标注和可靠性状态在事件里长什么样，不代表识别准确率。
真实识别请在装好 FunASR 的电脑上用 server + replay_file.py。

用法：uv run python scripts/run_demo.py 输出目录
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from classroom_speech.engines import AsrResult
from classroom_speech.pipeline import Session
from classroom_speech.sim import ClassroomRoom, Placement, fan_noise, scale_to_snr, synth_speech
from classroom_speech.stages import Profile

QUESTION = "把一个图形分成四块，每块是它的四分之一吗？"
SCRIPT = [
    # (说话人, 方位°, 距离 m, 与上一句结束的间隔 s（负数表示抢话）, 台词, 音色)
    ("教师", 0, 1.2, 0.5, "每块是四分之一吗？", {"voice": "cmn+m3", "pitch": 35, "speed": 175}),
    ("学生甲", -40, 2.5, 0.8, "有四块就是四分之一。", {"voice": "cmn+f3", "pitch": 70, "speed": 170}),
    ("学生乙", 35, 2.8, -1.4, "不对，要分得一样大。", {"voice": "cmn+f4", "pitch": 90, "speed": 175}),
    ("学生丙", -32, 2.2, 1.0, "我觉得是十分之一。", {"voice": "cmn", "pitch": 45, "speed": 165}),
    ("学生甲", -40, 2.5, 1.0, "那它没有平均分。", {"voice": "cmn+f3", "pitch": 70, "speed": 170}),
]


class ScriptByTimeAsr:
    """测试替身：返回与当前片段时间重叠最多、方位最近的那句台词。"""

    name = "oracle_script_by_time"

    def __init__(self, lines: list[dict]) -> None:
        self.lines, self.window = lines, None

    def transcribe(self, audio, sample_rate):
        if self.window is None:
            return None
        a, b, az = self.window

        def score(m):
            ov = max(0.0, min(b, m["end_s"] * 1000) - max(a, m["start_s"] * 1000))
            return ov / (m["end_s"] * 1000 - m["start_s"] * 1000) - abs(az - m["azimuth_deg"]) / 180

        best = max(self.lines, key=score)
        return AsrResult(text=best["text"], engine=self.name) if score(best) > 0.2 else None


class DemoSession(Session):
    def _emit_segment(self, seg_id, audio, azimuth, start_ms, end_ms, *args, **kw):
        self.asr.window = (start_ms, end_ms, float(azimuth))
        return super()._emit_segment(seg_id, audio, azimuth, start_ms, end_ms, *args, **kw)


def make_scene(out: Path):
    rng = np.random.default_rng(7)
    room = ClassroomRoom()
    placements, meta, prev_end = [], [], 0.0
    for who, az, dist, gap, text, voice in SCRIPT:
        s = synth_speech(text, voice)
        t0 = round(prev_end + gap, 2)
        prev_end = max(prev_end, t0 + len(s) / 16000)
        placements.append(Placement(s, az, dist, t0))
        meta.append({"speaker": who, "azimuth_deg": az, "start_s": t0, "end_s": round(t0 + len(s) / 16000, 2), "text": text})
    length = prev_end + 1.0
    images = room.render_each(placements, length)
    speech = sum(images)
    (fan,) = room.render_each([Placement(fan_noise(int(length * 16000) + 10, 16000, rng), 80, 3.5)], length)
    mix = speech + scale_to_snr(speech, fan, 5) + 0.002 * rng.standard_normal(speech.shape)
    mix = (mix / (np.max(np.abs(mix)) / 0.9)).astype(np.float32)
    sf.write(out / "demo_scene.wav", mix.T, 16000)
    (out / "demo_scene.json").write_text(json.dumps(
        {"data_origin": "simulated", "note": "espeak-ng 带调拼音合成语音 + 模拟教室混响（RT60 0.45 s）与风扇噪声（5 dB），非真实课堂",
         "question": QUESTION, "lines": meta}, ensure_ascii=False, indent=2))
    return mix, meta


def make_enrollment() -> dict:
    """课前每人在座位上读两句注册语（与课上台词不同）。"""
    room, rng, out = ClassroomRoom(), np.random.default_rng(8), {}
    for who, az, dist, _, _, voice in SCRIPT:
        if who in out:
            continue
        sp = np.concatenate([synth_speech(t, voice) for t in ("我们今天学习分数。", "老师，我想回答这个问题。")])
        (img,) = room.render_each([Placement(sp, az, dist, 0.3)], len(sp) / 16000 + 0.8)
        out[who] = (img + 0.002 * rng.standard_normal(img.shape)).astype(np.float32)
    return out


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    mix, meta = make_scene(out)
    enrollment = make_enrollment()
    for name, profile, enr in [("baseline", Profile.baseline(), None), ("integrated", Profile(), None),
                               ("integrated_enrolled", Profile(), enrollment)]:
        d = out / name
        d.mkdir(exist_ok=True)
        s = DemoSession(f"ses_demo_{name}", d, asr=ScriptByTimeAsr(meta), data_origin="simulated", profile=profile,
                        context={"question": QUESTION, "expected_terms": ["四分之一", "平均分"]}, enrollment=enr)
        for i in range(0, mix.shape[1], 1600):
            s.push(mix[:, i : i + 1600])
        s.end()
        with open(d / "events.jsonl", "w") as f:
            for e in s.events:
                f.write(e.model_dump_json(by_alias=True, exclude_none=True) + "\n")
        print(name, s.stages.origin)
        for e in s.events:
            if e.event_type == "source.position":
                az, spk = (r.value for r in e.sources)
                enr_match = (e.diagnostics or {}).get("enrolled_match")
                print(f"  {e.segment_id} {e.start_ms/1000:5.1f}–{e.end_ms/1000:5.1f}s  方位 {az:6.1f}°  {spk}" + (f"  注册匹配:{enr_match}" if enr_match else ""))
            elif e.event_type == "transcript.final":
                reasons = (e.diagnostics or {}).get("math_guard", {}).get("review_reasons", [])
                print(f"      {e.text}  [{e.reliability_state.value}{' 重叠' if e.overlap and e.overlap.present else ''}] {reasons}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "../../data/audio/demo"))
