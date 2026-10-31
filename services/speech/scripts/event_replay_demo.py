"""事件时间定位与上下文回溯演示：约 12 分钟合成课堂，Agent 在 00:10:23 报告一个事件，取前 30 秒、后 60 秒的上下文。

场景里刻意放进需要保留的状态：抢话重叠、一句无法识别的嘟囔、一段 8 秒断流（补静音，后续时间不漂移）、
窗口两端被截断的发言、窗口外的发言（不应出现）。转写用 run_demo.py 的测试替身 oracle_script_by_time
（按剧本时间返回台词），只演示时间轴与状态如何回传，不代表识别准确率；真实转写需在装好 FunASR 的电脑上跑。

用法：uv run python scripts/event_replay_demo.py 输出目录
输出：archive/（raw.wav、events.jsonl、timebase.json、处理音轨）、lesson_script.json、
      event_<id>/context.json + clip.wav + context.txt（每个 Agent 事件一份）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent))
from event_context import describe  # noqa: E402
from run_demo import DemoSession, ScriptByTimeAsr  # noqa: E402

from classroom_speech.sim import ClassroomRoom, Placement, fan_noise, synth_speech  # noqa: E402
from classroom_speech.timeline import TimelineIndex, format_clock, parse_clock, read_clip  # noqa: E402

VOICE = {"教师": {"voice": "cmn+m3", "pitch": 35, "speed": 175}, "学生甲": {"voice": "cmn+f3", "pitch": 70, "speed": 170},
         "学生乙": {"voice": "cmn+f4", "pitch": 90, "speed": 175}, "学生丙": {"voice": "cmn", "pitch": 45, "speed": 165}}
SEAT = {"教师": (0, 1.2), "学生甲": (-40, 2.5), "学生乙": (35, 2.8), "学生丙": (-32, 2.2)}
LESSON = [
    # (开始时间, 说话人, 台词, 识别器能否识别)
    ("00:01:00", "教师", "同学们好，今天我们学习分数。", True),
    ("00:09:51", "教师", "请大家看黑板上的图形，每块是四分之一吗？", True),  # 跨越窗口起点
    ("00:09:58", "学生甲", "有四块就是四分之一。", True),
    ("00:09:59.2", "学生乙", "不对，要分得一样大。", True),  # 抢话
    ("00:10:04", "学生丙", "我觉得是十分之一。", True),
    ("00:10:09", "学生甲", "那它没有平均分。", True),
    ("00:10:15", "学生乙", "你连这个都不会。", True),
    ("00:10:20", "学生丙", "嗯，我，我不知道。", False),  # 嘟囔：识别器返回空
    ("00:10:27", "教师", "大家先安静，我们一起再看一遍。", True),
    ("00:10:55", "教师", "四块要一样大，才是四分之一。", True),  # 断流之后
    ("00:11:08", "学生丙", "老师，我明白了。", True),
    ("00:11:21", "教师", "很好，下面我们做练习，先看第一题。", True),  # 跨越窗口终点
    ("00:11:40", "教师", "第一题请大家独立完成。", True),  # 窗口外
]
DROPOUT = ("00:10:40", 8000)  # 采集断流 8 秒：客户端上报，服务补静音
LENGTH_S = 11 * 60 + 50
SNR_DB = 8  # 发言段信噪比
AGENT_EVENTS = [
    # Agent 侧事件只给时间锚点与类型；语音模块不判断事件本身
    {"anchor_id": "agent_evt_001", "type": "student_emotion_abnormal", "at": "00:10:23", "before_s": 30, "after_s": 60},
    {"anchor_id": "agent_evt_002", "type": "answer_disagreement", "at": "00:09:59", "before_s": 5, "after_s": 10},
]


class LessonAsr(ScriptByTimeAsr):
    """剧本里标为“无法识别”的句子返回 None，模拟识别器对嘟囔给不出结果。"""

    def transcribe(self, audio, sample_rate):
        res = super().transcribe(audio, sample_rate)
        if res is None:
            return None
        line = next(m for m in self.lines if m["text"] == res.text)
        return res if line["recognizable"] else None


def make_lesson(out: Path):
    rng, room, sr = np.random.default_rng(11), ClassroomRoom(), 16000
    n = LENGTH_S * sr
    speech = np.zeros((2, n), np.float32)
    lines = []
    for at, who, text, ok in LESSON:
        s = synth_speech(text, VOICE[who])
        az, dist = SEAT[who]
        (img,) = room.render_each([Placement(s, az, dist, 0.0)], len(s) / sr + 0.6)
        a = parse_clock(at) * sr // 1000
        speech[:, a : a + img.shape[1]] += img[:, : n - a]
        lines.append({"speaker": who, "azimuth_deg": az, "start_s": a / sr, "end_s": round(a / sr + len(s) / sr, 2),
                      "start_clock": format_clock(a * 1000 // sr), "text": text, "recognizable": ok})
    active = np.abs(speech[0]) > 1e-3
    (fan,) = room.render_each([Placement(fan_noise(n + 10, sr, rng), 80, 3.5)], LENGTH_S)
    fan *= np.sqrt(np.mean(speech[0, active] ** 2) / (np.mean(fan[0] ** 2) * 10 ** (SNR_DB / 10)))
    mix = speech + fan + 0.002 * rng.standard_normal(speech.shape)
    mix = (mix / (np.max(np.abs(mix)) / 0.9)).astype(np.float32)
    gap_a = parse_clock(DROPOUT[0]) * sr // 1000
    mix[:, gap_a : gap_a + DROPOUT[1] * sr // 1000] = 0  # 这段音频在采集端丢失，不会送进服务
    (out / "lesson_script.json").write_text(json.dumps(
        {"data_origin": "simulated", "note": "espeak-ng 合成语音 + 模拟教室混响（RT60 0.45 s）与风扇噪声，非真实课堂",
         "dropout": {"start_clock": DROPOUT[0], "duration_ms": DROPOUT[1]}, "lines": lines}, ensure_ascii=False, indent=2))
    return mix, lines


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    mix, lines = make_lesson(out)
    archive = out / "archive"
    s = DemoSession("ses_lesson_demo", archive, asr=LessonAsr(lines), data_origin="simulated",
                    context={"question": "每块是四分之一吗？", "expected_terms": ["四分之一", "平均分"]},
                    capture_started_unix_ms=1_793_000_000_000)
    gap_a, gap_n = parse_clock(DROPOUT[0]) * 16, DROPOUT[1] * 16
    for i in range(0, mix.shape[1], 1600):
        if gap_a <= i < gap_a + gap_n:
            if i == gap_a:
                s.mark_gap(DROPOUT[1], "stream_dropout")  # 断流期间没有音频到达；恢复时客户端上报缺失时长
            continue
        s.push(mix[:, i : i + 1600])
    s.end()

    tl = TimelineIndex.from_archive(archive)  # 与服务重启后读到的一样
    for e in AGENT_EVENTS:
        w = tl.window(parse_clock(e["at"]), e["before_s"] * 1000, e["after_s"] * 1000)
        d = out / f"event_{e['anchor_id']}"
        d.mkdir(exist_ok=True)
        (d / "context.json").write_text(json.dumps({"agent_event": e, **w}, ensure_ascii=False, indent=2))
        clip, sr = read_clip(archive / "raw.wav", w["window"]["from_ms"], w["window"]["to_ms"])
        sf.write(d / "clip.wav", clip, sr)
        text = describe(w, e)
        (d / "context.txt").write_text(text + "\n")
        print(text, "\n")
    # 自检：对照剧本逐句核对事件 1 的窗口（测试替身返回的就是剧本原句，可按文本对齐）
    w = tl.window(parse_clock("00:10:23"))
    lo, hi = w["requested"]["from_ms"], w["requested"]["to_ms"]
    report = []
    for m in lines:
        inside = m["start_s"] * 1000 < hi and lo < m["end_s"] * 1000
        found = [u for u in w["utterances"] if u["text"] == m["text"]]
        hit = [u for u in w["utterances"] if u["start_ms"] < m["end_s"] * 1000 and m["start_s"] * 1000 < u["end_ms"]]
        if not inside:
            status = "窗口外，未返回" if not found else "窗口外却被返回"
        elif found:
            u = found[0]
            status = f"找到 {u['segment_id']}，起点误差 {u['start_ms'] - m['start_s'] * 1000:+.0f} ms"
        elif not m["recognizable"] and hit:
            status = f"找到 {hit[0]['segment_id']}，状态 {hit[0]['transcript_state']}（剧本即为无法识别）"
        elif hit:
            status = f"漏检：音频落在 {hit[0]['segment_id']} 里，但没被单独切出（多半是抢话未检出重叠）"
        else:
            status = "漏检：时间轴上没有对应发言"
        report.append({"start_clock": m["start_clock"], "speaker": m["speaker"], "text": m["text"], "check": status})
        print(f"  {m['start_clock'][3:]} {m['speaker']} {m['text']}  → {status}")
    (out / "self_check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "../../data/audio/event_demo"))
