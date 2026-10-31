"""时间轴索引与上下文回溯：按时间范围取回音频、转写、匿名说话人、方位和缺失状态。

统一时间基准：会话时间 = 累计音频样本数 / 采样率（毫秒，从会话第一个样本起算），与网络到达时间无关。
转写、声源、重叠、断流事件都落在这一条轴上；原始双通道音频 raw.wav 的第 n 个样本就是 n/16 ms。

本模块只回答“这段时间里录到了什么”，不判断事件原因。时间上接近不代表因果，由 Agent 与教师核验。
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from .events import PROTOCOL_VERSION, EventType, SpeechEvent

WINDOW_SCHEMA = "speech.window.v0.1"

# 覆盖状态，按优先级从高到低：窗口里每一毫秒恰好落在其中一种
NOT_RECORDED = "not_recorded"  # 会话开始前 / 录音尚未到达的未来
GAP = "gap"  # 采集断流或上报的缺失区间，音频是补的静音
NOT_PROCESSED = "not_processed_yet"  # 已录到但切句还没结束（实时会话里正在说的那句）
OVERLAP = "overlap"  # 两段以上发言同时进行
SPEECH = "speech"
NO_SPEECH = "no_speech_detected"  # 录到了，但 VAD 判为无人发言（不等于确认安静）

_TRANSCRIPT_STATE = {"asr_unavailable": "asr_unavailable", "no_speech_recognized": "unrecognized"}


def parse_clock(value: str | int | float) -> int:
    """'00:10:23' / '10:23' / '623.5'（秒）→ 会话毫秒。整数按毫秒处理。"""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value * 1000))
    parts = [float(p) for p in str(value).strip().split(":")]
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return int(round(seconds * 1000))


def format_clock(ms: int) -> str:
    sign, ms = ("-", -int(ms)) if ms < 0 else ("", int(ms))
    s, milli = divmod(ms, 1000)
    h, rem = divmod(s, 3600)
    return f"{sign}{h:02d}:{rem // 60:02d}:{rem % 60:02d}.{milli:03d}"


@dataclass
class Utterance:
    segment_id: str
    start_ms: int
    end_ms: int
    revision: int | None = None
    text: str | None = None
    transcript_state: str = "pending"  # recognized | unrecognized | asr_unavailable | pending | retracted
    reliability_state: str | None = None
    status: str | None = None
    speaker: dict | None = None
    azimuth: dict | None = None
    overlap_with: list[str] = field(default_factory=list)
    audio_ref: list[dict] = field(default_factory=list)
    enrolled_match: str | None = None
    event_ids: list[str] = field(default_factory=list)


@dataclass
class TimelineIndex:
    session_id: str
    sample_rate: int
    recorded_until_ms: int
    processed_until_ms: int
    ended: bool
    data_origin: str
    utterances: list[Utterance]
    gaps: list[dict]
    timebase: dict

    # ---------- 构建 ----------
    @classmethod
    def build(cls, events: list[SpeechEvent], *, session_id: str, sample_rate: int, recorded_until_ms: int,
              processed_until_ms: int, ended: bool, timebase: dict | None = None) -> "TimelineIndex":
        utts: dict[str, Utterance] = {}
        gaps: list[dict] = []
        origin = events[0].data_origin if events else "live"
        for ev in sorted(events, key=lambda e: e.sequence):
            if ev.event_type == EventType.STREAM_STATUS and ev.gap is not None:
                gaps.append({"start_ms": ev.gap.start_ms, "end_ms": ev.gap.end_ms, "reason": ev.gap.reason, "event_id": ev.event_id})
                continue
            if ev.segment_id is None:
                continue
            u = utts.get(ev.segment_id)
            if u is None:
                u = utts[ev.segment_id] = Utterance(ev.segment_id, ev.start_ms or 0, ev.end_ms or 0)
            u.event_ids.append(ev.event_id)
            if ev.event_type == EventType.SOURCE_POSITION:
                for r in ev.sources:
                    rec = {"source_id": r.source_id, "reliability_state": r.reliability_state.value, "rebind_hint": r.rebind_hint}
                    if r.kind == "azimuth":
                        u.azimuth = {"deg": r.value, "reference": r.reference, **rec,
                                     "doa_confidence": (ev.diagnostics or {}).get("doa_confidence")}
                    else:
                        u.speaker = {"label": r.value, **rec}
                u.enrolled_match = (ev.diagnostics or {}).get("enrolled_match")
            elif ev.event_type in (EventType.TRANSCRIPT_FINAL, EventType.TRANSCRIPT_REVISED):
                if u.revision is not None and (ev.revision or 0) < u.revision:
                    continue  # 只保留最新修订
                u.revision, u.text, u.status = ev.revision, ev.text, ev.status
                u.start_ms, u.end_ms = ev.start_ms or u.start_ms, ev.end_ms or u.end_ms
                u.reliability_state = ev.reliability_state.value if ev.reliability_state else None
                u.transcript_state = "recognized" if ev.text else _TRANSCRIPT_STATE.get(ev.status or "", "unrecognized")
                u.overlap_with = list(ev.overlap.with_segments) if ev.overlap else []
                u.audio_ref = [a.model_dump() for a in ev.audio_ref]
            elif ev.event_type == EventType.TRANSCRIPT_RETRACTED:
                u.transcript_state, u.text = "retracted", None  # 撤回的发言保留占位，不从时间轴上消失
        return cls(session_id, sample_rate, recorded_until_ms, processed_until_ms, ended, origin,
                   sorted(utts.values(), key=lambda u: (u.start_ms, u.segment_id)), gaps, timebase or {})

    @classmethod
    def from_session(cls, s) -> "TimelineIndex":
        return cls.build(list(s.events), session_id=s.session_id, sample_rate=s.cfg.sample_rate,
                         recorded_until_ms=s.recorded_ms(), processed_until_ms=s.processed_ms(), ended=s.ended,
                         timebase=s.timebase())

    @classmethod
    def from_archive(cls, archive_dir: Path) -> "TimelineIndex":
        """从会话存档目录重建（服务重启后、或离线分析时用）：events.jsonl + raw.wav [+ timebase.json]。"""
        archive_dir = Path(archive_dir)
        events = [SpeechEvent.model_validate_json(line) for line in
                  (archive_dir / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        info = sf.info(str(archive_dir / "raw.wav"))
        tb_path = archive_dir / "timebase.json"
        timebase = json.loads(tb_path.read_text(encoding="utf-8")) if tb_path.exists() else {}
        recorded = int(info.frames * 1000 / info.samplerate)
        ended = any(e.event_type == EventType.SESSION_ENDED for e in events)
        sid = events[0].session_id if events else archive_dir.name
        return cls.build(events, session_id=sid, sample_rate=int(info.samplerate), recorded_until_ms=recorded,
                         processed_until_ms=recorded if ended else max([e.end_ms or 0 for e in events] + [0]),
                         ended=ended, timebase=timebase)

    # ---------- 查询 ----------
    def segment(self, segment_id: str) -> Utterance | None:
        return next((u for u in self.utterances if u.segment_id == segment_id), None)

    def coverage(self, a: int, b: int) -> list[dict]:
        """把 [a, b) 切成互不重叠的区间，每段标注覆盖状态和当时在说话的片段。"""
        cuts = {a, b, 0, self.recorded_until_ms, self.processed_until_ms}
        for u in self.utterances:
            cuts |= {u.start_ms, u.end_ms}
        for g in self.gaps:
            cuts |= {g["start_ms"], g["end_ms"]}
        cuts = sorted(c for c in cuts if a <= c <= b)
        out: list[dict] = []
        for lo, hi in zip(cuts, cuts[1:]):
            if hi <= lo:
                continue
            active = [u.segment_id for u in self.utterances if u.start_ms < hi and lo < u.end_ms]
            gap = next((g for g in self.gaps if g["start_ms"] < hi and lo < g["end_ms"]), None)
            if hi <= 0 or lo >= self.recorded_until_ms:
                state = NOT_RECORDED
            elif gap is not None:
                state = GAP
            elif len(active) >= 2:
                state = OVERLAP
            elif active:
                state = SPEECH
            elif lo >= self.processed_until_ms:
                state = NOT_PROCESSED
            else:
                state = NO_SPEECH
            item = {"from_ms": lo, "to_ms": hi, "state": state, "segments": active}
            if gap is not None and state == GAP:
                item["reason"] = gap["reason"]
            prev = out[-1] if out else None
            if prev and prev["state"] == item["state"] and prev["segments"] == active and prev.get("reason") == item.get("reason"):
                prev["to_ms"] = hi
            else:
                out.append(item)
        return out

    def range(self, from_ms: int, to_ms: int, *, anchor_ms: int | None = None, audio_base_url: str | None = None) -> dict:
        """时间范围查询：窗口内（含跨越边界的）全部发言 + 覆盖状态 + 音频片段定位。"""
        if to_ms <= from_ms:
            raise ValueError("to_ms 必须大于 from_ms")
        lo, hi = max(from_ms, 0), min(to_ms, self.recorded_until_ms)
        clip = None
        if hi > lo:
            clip = {"raw_ref": f"aud_{self.session_id}_raw", "from_ms": lo, "to_ms": hi, "duration_ms": hi - lo,
                    "channels": "mic0 单声道回放；stereo 为原始双通道",
                    "note": "片段第 0 毫秒 = 会话时间 from_ms；发言的 offset_in_clip_ms 即播放器内位置"}
            if audio_base_url is not None:
                clip["url"] = f"{audio_base_url}/v1/audio/{self.session_id}/clip?from_ms={lo}&to_ms={hi}"
        utts = []
        for u in self.utterances:
            if not (u.start_ms < to_ms and from_ms < u.end_ms):
                continue
            d = {"segment_id": u.segment_id, "start_ms": u.start_ms, "end_ms": u.end_ms,
                 "start_clock": format_clock(u.start_ms), "offset_in_clip_ms": u.start_ms - lo if clip else None,
                 "clipped_by_window": u.start_ms < from_ms or u.end_ms > to_ms,
                 "text": u.text, "transcript_state": u.transcript_state, "reliability_state": u.reliability_state,
                 "status": u.status, "revision": u.revision, "speaker": u.speaker, "azimuth": u.azimuth,
                 "overlap": {"present": bool(u.overlap_with), "with": u.overlap_with},
                 "audio_ref": u.audio_ref, "event_ids": u.event_ids}
            if u.enrolled_match is not None:
                d["enrolled_match"] = u.enrolled_match  # 只是线索，身份由教师确认
            if anchor_ms is not None:
                d["relation"] = "before" if u.end_ms <= anchor_ms else "after" if u.start_ms > anchor_ms else "spans_anchor"
                d["distance_to_anchor_ms"] = 0 if d["relation"] == "spans_anchor" else (
                    anchor_ms - u.end_ms if d["relation"] == "before" else u.start_ms - anchor_ms)
            utts.append(d)
        for i, d in enumerate(utts):
            d["order"] = i + 1
        cov = self.coverage(from_ms, to_ms)
        dur = lambda st: sum(c["to_ms"] - c["from_ms"] for c in cov if c["state"] == st)  # noqa: E731
        states = [d["transcript_state"] for d in utts]
        result = {
            "schema": WINDOW_SCHEMA, "protocol_version": PROTOCOL_VERSION, "session_id": self.session_id,
            "data_origin": self.data_origin, "timebase": self.timebase,
            "requested": {"from_ms": from_ms, "to_ms": to_ms},
            "window": {"from_ms": lo, "to_ms": max(hi, lo), "from_clock": format_clock(lo), "to_clock": format_clock(max(hi, lo))},
            "recorded_until_ms": self.recorded_until_ms, "processed_until_ms": self.processed_until_ms,
            "session_ended": self.ended, "complete": self.ended or to_ms <= self.processed_until_ms,
            "audio": clip, "utterances": utts, "coverage": cov,
            "summary": {
                "utterances": len(utts), "overlapped": sum(d["overlap"]["present"] for d in utts),
                "recognized": states.count("recognized"),
                "unrecognized": len(states) - states.count("recognized") - states.count("pending"),
                "pending": states.count("pending"),
                "needs_review": sum(d["reliability_state"] in ("needs_review", "undetermined", "failed") for d in utts),
                "speakers": sorted({d["speaker"]["label"] for d in utts if d["speaker"]}),
                **{f"{st}_ms": dur(st) for st in (SPEECH, OVERLAP, NO_SPEECH, GAP, NOT_RECORDED, NOT_PROCESSED)},
            },
            "notes": ["语音模块只给出时间范围内录到的内容；时间接近不代表因果，结论需 Agent 标注证据并由教师核验。",
                      "匿名说话人仅会话内有效，不是真实身份；声源方位是线索。"],
        }
        if anchor_ms is not None:
            result["anchor"] = {"at_ms": anchor_ms, "at_clock": format_clock(anchor_ms),
                                "before_ms": anchor_ms - from_ms, "after_ms": to_ms - anchor_ms,
                                "within_recording": 0 <= anchor_ms <= self.recorded_until_ms}
        return result

    def window(self, at_ms: int, before_ms: int = 30_000, after_ms: int = 60_000, **kw) -> dict:
        """以事件时间为中心取上下文：[at_ms - before_ms, at_ms + after_ms)。"""
        if before_ms < 0 or after_ms < 0:
            raise ValueError("before_ms / after_ms 不能为负")
        return self.range(at_ms - before_ms, at_ms + after_ms, anchor_ms=at_ms, **kw)


def read_clip(raw_path: Path, from_ms: int, to_ms: int, channels: str = "mic0") -> tuple[np.ndarray, int]:
    """从原始录音里切出 [from_ms, to_ms)，按样本定位，不重编码。返回 (N,) 或 (N, 2)。"""
    with sf.SoundFile(str(raw_path)) as f:
        sr = f.samplerate
        a = max(int(from_ms * sr / 1000), 0)
        b = min(int(to_ms * sr / 1000), f.frames)
        if b <= a:
            return np.zeros((0, 2) if channels == "stereo" else 0, np.float32), sr
        f.seek(a)
        x = f.read(b - a, dtype="float32", always_2d=True)
    return (x if channels == "stereo" else x[:, 0]), sr


def clip_wav_bytes(raw_path: Path, from_ms: int, to_ms: int, channels: str = "mic0") -> bytes:
    x, sr = read_clip(raw_path, from_ms, to_ms, channels)
    buf = io.BytesIO()
    sf.write(buf, x, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def resolve_audio_ref(archive_dir: Path, session_id: str, ref_id: str) -> Path | None:
    """把事件里的 audio_ref.id 映射到存档文件：aud_{sid}_raw → raw.wav；aud_{sid}_{seg}_{kind} → {seg}_{kind}.wav。"""
    prefix = f"aud_{session_id}_"
    if not ref_id.startswith(prefix):
        return None
    name = ref_id[len(prefix):]
    path = archive_dir / ("raw.wav" if name == "raw" else f"{name}.wav")
    if path.parent != archive_dir or not path.exists():
        return None
    return path
