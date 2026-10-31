"""会话流水线：接收双通道 PCM 块 → 切句 → 定位 → 去噪 / 分离 → 转写守卫 → 契约事件。

时间轴以累计样本数为准（契约 §3：不用网络到达时间代替音频时间）。断流时用 mark_gap 补静音，
保证之后的样本仍落在正确的会话时间上。原始音频 raw.wav 与事件 events.jsonl 边收边落盘，
供 timeline.py 按时间范围回溯（服务重启后也能从存档重建）。
各阶段实现由 stages.build_stages(profile) 提供：四个优化方向的模块优先，缺失时退回基准。
"""

from __future__ import annotations

import inspect
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from .engines import AsrEngine
from .events import AudioRef, Gap, Overlap, Reliability, SourceRecord, SpeechEvent, EventType
from .separation import mask_separate
from .spatial import ArrayConfig, quiet_cross_spectrum, to_stft
from .stages import Profile, as_report, build_stages

_RANK = {Reliability.USABLE: 0, Reliability.NEEDS_REVIEW: 1, Reliability.UNDETERMINED: 2, Reliability.FAILED: 3}


def most_conservative(*states) -> Reliability:
    return max((Reliability(s) for s in states if s is not None), key=_RANK.__getitem__, default=Reliability.USABLE)


@dataclass
class VadConfig:
    frame_ms: int = 30
    start_db: float = 9.0  # 高于噪声底多少 dB 视为语音
    end_silence_ms: int = 600
    min_segment_ms: int = 400
    max_segment_ms: int = 15000
    pad_ms: int = 200


@dataclass
class Session:
    session_id: str
    archive_dir: Path
    asr: AsrEngine | None = None
    data_origin: str = "live"
    cfg: ArrayConfig = field(default_factory=ArrayConfig)
    vad: VadConfig = field(default_factory=VadConfig)
    profile: Profile = field(default_factory=Profile)
    context: dict | None = None  # 当前题目上下文，只用于候选排序与核验提示，不改写原文
    enrollment: dict | None = None  # 可选声纹注册 {label: 音频}
    events: list[SpeechEvent] = field(default_factory=list)
    ended: bool = False
    capture_started_unix_ms: int | None = None  # 采集端给出的第 0 个样本的墙钟时间；不给则取首帧到达时间（近似）
    channels: int = 2  # 实际采集通道数；单声道的内部复制不构成麦克风阵列

    def __post_init__(self) -> None:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._raw = sf.SoundFile(self.archive_dir / "raw.wav", "w", self.cfg.sample_rate, 2, "PCM_16")
        self._raw_lock = threading.Lock()
        self._event_log = open(self.archive_dir / "events.jsonl", "w", encoding="utf-8")
        self._clock_source = "client" if self.capture_started_unix_ms is not None else None
        self._buffer = np.zeros((2, 0), np.float32)
        self._buffer_start = 0  # 缓冲区首样本在会话时间轴上的位置
        self._samples = 0
        self._noise_db: float | None = None
        self._noise_cross: np.ndarray | None = None  # 语音前静音的平均互谱：持续噪声的空间指纹
        self._noise_power: np.ndarray | None = None  # 同一静音段 mic0 的平均功率谱：噪声底先验
        self._seg_start: int | None = None
        self._silence = 0
        self._seg_counter = 0
        self._lock = threading.Lock()
        self.stages = build_stages(self.profile)
        self.speakers = self.stages.make_tracker()
        self.guard = self.stages.guard_cls(self.asr)
        self.listeners: list = []

    # ---------- 事件 ----------
    def _emit(self, **kw) -> SpeechEvent:
        with self._lock:
            seq = len(self.events) + 1
            ev = SpeechEvent(
                session_id=self.session_id, event_id=f"evt_{uuid.uuid4().hex[:12]}", sequence=seq, data_origin=self.data_origin, **kw
            )
            self.events.append(ev)
            self._event_log.write(ev.model_dump_json(by_alias=True, exclude_none=True) + "\n")
            self._event_log.flush()
        for listener in list(self.listeners):
            listener(ev)
        return ev

    def events_after(self, sequence: int) -> list[SpeechEvent]:
        return [e for e in self.events if e.sequence > sequence]

    def _ms(self, sample: int) -> int:
        return int(sample * 1000 / self.cfg.sample_rate)

    # ---------- 时间基准 ----------
    def recorded_ms(self) -> int:
        return self._ms(self._samples)

    def processed_ms(self) -> int:
        """此前的音频都已切句处理完；之后是正在说的那句或还没到的音频。"""
        return self._ms(self._seg_start) if self._seg_start is not None else self.recorded_ms()

    def timebase(self) -> dict:
        return {"unit": "ms", "origin": "session_sample_0", "sample_rate": self.cfg.sample_rate,
                "input_channels": self.channels, "stored_channels": 2,
                "capture_started_unix_ms": self.capture_started_unix_ms, "wall_clock_source": self._clock_source,
                "note": "会话毫秒 = 样本序号 / 采样率；墙钟只用于换算，可能有采集端时钟漂移"}

    def _write_timebase(self) -> None:
        (self.archive_dir / "timebase.json").write_text(json.dumps(self.timebase(), ensure_ascii=False), encoding="utf-8")

    def to_session_ms(self, unix_ms: int) -> int:
        """墙钟 → 会话毫秒（近似）。Agent 优先直接用事件里的会话毫秒。"""
        if self.capture_started_unix_ms is None:
            raise ValueError("会话还没有收到音频，无法换算墙钟时间")
        return int(unix_ms - self.capture_started_unix_ms)

    def flush_raw(self) -> None:
        """让正在录的 raw.wav 头部与已写样本一致，录音过程中也能按时间切片。"""
        with self._raw_lock:
            if not self._raw.closed:
                self._raw.flush()

    # ---------- 输入 ----------
    def push_pcm(self, pcm: bytes, channels: int = 2) -> None:
        """接收 s16le 交错 PCM。单声道输入会复制成两路，并在位置事件中标为无法判断。"""
        if channels not in (1, 2):
            raise ValueError("只接受单声道或双声道输入")
        if self._samples and channels != self.channels:
            raise ValueError("会话内不能改变实际采集通道数")
        self.channels = channels
        x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        x = x.reshape(-1, channels).T
        if channels == 1:
            x = np.vstack([x, x])
        self.push(x[:2])

    def push(self, x: np.ndarray) -> None:
        if self.capture_started_unix_ms is None:
            self.capture_started_unix_ms, self._clock_source = int(time.time() * 1000), "server_first_frame"
        if self._samples == 0:
            self._write_timebase()
        with self._raw_lock:
            self._raw.write(x.T)
        self._buffer = np.concatenate([self._buffer, x], axis=1)
        frame = int(self.cfg.sample_rate * self.vad.frame_ms / 1000)
        # 逐帧做能量 VAD；缓冲区只保留未结束片段 + 回看余量
        pos = self._samples
        self._samples += x.shape[1]
        while pos + frame <= self._samples:
            local = pos - self._buffer_start
            seg = self._buffer[0, local : local + frame]
            db = 10 * np.log10(np.mean(seg**2) + 1e-10)
            # 噪声底：遇到更安静的帧立即下调，否则缓慢上浮，适应教室噪声变化
            if self._noise_db is None or db < self._noise_db:
                self._noise_db = db
            elif db < self._noise_db + 3:
                self._noise_db = 0.95 * self._noise_db + 0.05 * db
            else:
                self._noise_db += 0.002
            is_speech = db > self._noise_db + self.vad.start_db
            if self._seg_start is None and is_speech:
                self._seg_start = max(pos - int(self.vad.pad_ms * self.cfg.sample_rate / 1000), self._buffer_start)
                self._silence = 0
                self._update_noise_print(self._buffer[:, : self._seg_start - self._buffer_start])
            elif self._seg_start is not None:
                self._silence = 0 if is_speech else self._silence + self.vad.frame_ms
                long_enough = self._ms(pos - self._seg_start) >= self.vad.max_segment_ms
                if self._silence >= self.vad.end_silence_ms or long_enough:
                    self._finish_segment(pos + frame)
            pos += frame
        keep_from = self._seg_start if self._seg_start is not None else self._samples - self.cfg.sample_rate
        keep_from = max(keep_from, self._buffer_start)
        self._buffer = self._buffer[:, keep_from - self._buffer_start :]
        self._buffer_start = keep_from

    def _update_noise_print(self, quiet: np.ndarray) -> None:
        if quiet.shape[1] < self.cfg.sample_rate // 4:
            return
        spec = to_stft(quiet, self.cfg)
        cross = quiet_cross_spectrum(spec, 100)
        power = np.mean(np.abs(spec[0]) ** 2, axis=1)
        self._noise_cross = cross if self._noise_cross is None else 0.7 * self._noise_cross + 0.3 * cross
        self._noise_power = power if self._noise_power is None else 0.7 * self._noise_power + 0.3 * power

    # ---------- 片段处理 ----------
    def _finish_segment(self, end_sample: int) -> None:
        start = self._seg_start
        self._seg_start = None
        if start is None or self._ms(end_sample - start) < self.vad.min_segment_ms:
            return
        a, b = start - self._buffer_start, end_sample - self._buffer_start
        self.process_segment(self._buffer[:, a:b], start)

    def process_segment(self, x: np.ndarray, start_sample: int) -> list[SpeechEvent]:
        start_ms, end_ms = self._ms(start_sample), self._ms(start_sample + x.shape[1])
        if self.channels == 1:
            # 复制只满足内部缓冲区形状。没有阵列时保留原音并转写，不运行空间分流或身份跟踪。
            return self._emit_segment(
                self._next_segment_id(), x[0], None, start_ms, end_ms, [], "raw",
            )
        spec = to_stft(x, self.cfg)
        loc = self.stages.localize(spec, self.cfg, noise_cross=self._noise_cross, max_sources=2)
        azimuths = list(loc.azimuths)
        conf = dict(zip(azimuths, loc.confidence))
        out: list[SpeechEvent] = []
        enrolled = bool(self.enrollment) and self.stages.origin.get("separation") == "contrib"
        if len(azimuths) >= 2 or enrolled:
            # 多个方位，或有课前声纹注册（按注册的人分路，可多于方位数）：按方位分流（重叠处分离，单人处整帧路由），再在每一路里切出发言
            streams, report = self.stages.separate(
                x, azimuths, self.cfg, noise_cross=self._noise_cross, localization=loc, enrollment=self.enrollment
            )
            report = as_report(report)
            # 声纹注册时路数可多于方位数：每路方位 / 注册标签由分离报告给出
            stream_az = list(getattr(report, "stream_azimuths", None) or azimuths)
            stream_lab = list(getattr(report, "stream_labels", None) or [None] * len(streams))
            if enrolled and len(azimuths) >= 2 and len(streams) >= 2:
                stream_az = self._anchor_streams(x, streams, azimuths)
            regions = [
                (k, a, b) for k, stream in enumerate(streams) for a, b in self._active_regions(stream)
            ]
            ids = {r: self._next_segment_id() for r in sorted(regions, key=lambda r: r[1])}
            for (k, a, b), seg_id in ids.items():
                others = [ids[o] for o in ids if o[0] != k and o[1] < b and a < o[2]]
                az_k, c_k = self._region_azimuth(loc, stream_az[k], a, b, overlapped=bool(others))
                audio, kind = streams[k][a:b], "separated" if others else "denoised"
                if not others and self.profile.refine_single:
                    # 只有一个人在说的区间：不用分离掩码，回到原始双通道做空间—频谱去噪
                    y, diag = self.stages.denoise(x[:, a:b], self.cfg, theta_deg=az_k, doa_confidence=c_k,
                                                  noise_cross=self._noise_cross, noise_power=self._noise_power)
                    audio, kind = (x[0, a:b], "raw") if diag.get("fallback_to_raw") else (y, "denoised")
                out += self._emit_segment(seg_id, audio, az_k, start_ms + self._ms(a), start_ms + self._ms(b),
                                          others, kind, c_k, enrolled=stream_lab[k])
            if regions:
                return out
        az0 = azimuths[0] if azimuths else None
        c0 = conf.get(az0) if az0 is not None else None
        c0 = None if c0 is None or np.isnan(c0) else float(c0)
        denoised, diag = self.stages.denoise(x, self.cfg, theta_deg=az0, doa_confidence=c0, noise_cross=self._noise_cross,
                                             noise_power=self._noise_power)
        az = az0 if az0 is not None else diag["target_azimuth_deg"]
        use = x[0] if diag.get("fallback_to_raw") else denoised  # 质量门控：压得过狠就回退原音频
        kind = "denoised" if use is denoised else "raw"
        out += self._emit_segment(self._next_segment_id(), use, az, start_ms, end_ms, [], kind, c0)
        return out

    def _anchor_streams(self, x: np.ndarray, streams: np.ndarray, azimuths: list[float]) -> list[float]:
        """方位锚定对齐（基准创新点 3）用于声纹分路：注册座位会过时（换座），且注册时的方位估计不可靠；
        改为把每一路与“指向本次各定位峰的锚定流”做相关，归到最像的那个方位。路数可多于方位数。"""
        anchors = mask_separate(x, azimuths, self.cfg)

        def corr(u: np.ndarray, v: np.ndarray) -> float:
            u, v = u - u.mean(), v - v.mean()
            return float(abs(u @ v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-12))

        return [float(azimuths[int(np.argmax([corr(st, an) for an in anchors]))]) for st in streams]

    def _region_azimuth(self, loc, stream_az: float, a: int, b: int, overlapped: bool) -> tuple[float, float | None]:
        """一个发言区间的方位：单人区间取定位结果的逐帧中位数；重叠区间取离该路最近的定位峰。

        声纹注册给的是注册时的座位，学生换座后会过时，所以方位总以本次定位为准。
        """
        fa, fb = a // self.cfg.hop, max(b // self.cfg.hop, a // self.cfg.hop + 1)
        fz, fc = loc.frame_azimuth[fa:fb], loc.frame_confidence[fa:fb]
        if not overlapped and np.isfinite(fz).sum() >= 5:
            c = float(np.nanmean(fc)) if np.isfinite(fc).any() else None
            return float(np.nanmedian(fz)), c
        peaks = [p for p in loc.azimuths if np.isfinite(p)]
        if not peaks:
            return (stream_az if np.isfinite(stream_az) else 0.0), None
        ref = stream_az if np.isfinite(stream_az) else float(np.nanmedian(fz)) if np.isfinite(fz).any() else peaks[0]
        i = int(np.argmin([abs(p - ref) for p in peaks]))
        if np.isfinite(stream_az) and abs(peaks[i] - stream_az) > 20:
            return float(stream_az), 0.0  # 定位没看到这一路（被重叠的另一人盖住）：用注册座位方位，置信度记 0
        c = loc.confidence[i] if i < len(loc.confidence) else None
        return float(peaks[i]), (None if c is None or not np.isfinite(c) else float(c))

    def _active_regions(self, y: np.ndarray, rel_db: float = -18.0) -> list[tuple[int, int]]:
        """在一路分离输出里找连续发言区间（样本下标），短停顿合并，过短的丢弃。"""
        frame = int(0.03 * self.cfg.sample_rate)
        n = len(y) // frame
        if n == 0:
            return []
        db = 10 * np.log10(np.mean(y[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-10)
        db = np.convolve(db, np.ones(5) / 5, mode="same")
        active = db > db.max() + rel_db
        regions, start, gap = [], None, 0
        max_gap, min_len = int(self.vad.end_silence_ms / 30), int(self.vad.min_segment_ms / 30)
        for i, on in enumerate(active):
            if on:
                start = i if start is None else start
                gap = 0
            elif start is not None:
                gap += 1
                if gap > max_gap:
                    regions.append((start, i - gap + 1))
                    start, gap = None, 0
        if start is not None:
            regions.append((start, n - gap))
        pad = 5
        return [(max(a - pad, 0) * frame, min(b + pad, n) * frame) for a, b in regions if b - a >= min_len]

    def _next_segment_id(self) -> str:
        self._seg_counter += 1
        return f"seg_{self._seg_counter:04d}"

    def _emit_segment(self, seg_id, audio, azimuth, start_ms, end_ms, overlap_with, kind, doa_conf=None, enrolled=None) -> list[SpeechEvent]:
        doa_conf = None if doa_conf is None or np.isnan(doa_conf) else float(doa_conf)
        if azimuth is None:
            position = self._mono_position(seg_id, start_ms, end_ms)
        else:
            position = self._spatial_position(
                seg_id, audio, azimuth, start_ms, end_ms, overlap_with, doa_conf, enrolled,
            )
        events = [position]
        refs = [AudioRef(id=f"aud_{self.session_id}_raw", kind="raw")]
        if kind != "raw":
            refs.append(AudioRef(
                id=f"aud_{self.session_id}_{seg_id}_{kind}", kind=kind, offset_ms=start_ms,
                note="处理音轨，原音频不被覆盖",
            ))
            sf.write(self.archive_dir / f"{seg_id}_{kind}.wav", audio, self.cfg.sample_rate)
        overlap = Overlap(present=bool(overlap_with), with_segments=overlap_with)
        ctx = dict(self.context or {}, start_ms=start_ms, end_ms=end_ms, overlap=bool(overlap_with))
        result = self.guard.transcribe(audio, self.cfg.sample_rate, context=ctx) if self.asr else None
        common = dict(
            event_type=EventType.TRANSCRIPT_FINAL, segment_id=seg_id, revision=1,
            start_ms=start_ms, end_ms=end_ms, source_ref=position.source_ref, audio_ref=refs, overlap=overlap,
        )
        if result is None or not result.text:
            reason = "asr_unavailable" if self.asr is None else "no_speech_recognized"
            events.append(self._emit(
                **common, reliability_state=Reliability.FAILED if self.asr is None else Reliability.UNDETERMINED,
                status=reason,
            ))
        else:
            state = most_conservative(Reliability.NEEDS_REVIEW if overlap_with else None, result.reliability)
            diag = {"engine": result.engine, "audio_kind": kind}
            if hasattr(result, "diagnostics"):
                diag.update(result.diagnostics())
            events.append(self._emit(**common, text=result.text, reliability_state=state, diagnostics=diag))
        return events

    def _mono_position(self, seg_id: str, start_ms: int, end_ms: int) -> SpeechEvent:
        source = SourceRecord(
            source_id=f"src_unknown_{seg_id}", kind="anon_speaker", value="unknown", unit="label",
            reference="session", valid_from_ms=start_ms, valid_to_ms=end_ms,
            reliability_state=Reliability.UNDETERMINED,
        )
        return self._emit(
            event_type=EventType.SOURCE_POSITION, segment_id=seg_id, start_ms=start_ms, end_ms=end_ms,
            source_ref=[source.source_id], sources=[source], reliability_state=Reliability.UNDETERMINED,
            status="mono_position_unavailable", diagnostics={"input_channels": 1},
        )

    def _spatial_position(
        self, seg_id: str, audio: np.ndarray, azimuth: float, start_ms: int, end_ms: int,
        overlap_with: list[str], doa_conf: float | None, enrolled: str | None,
    ) -> SpeechEvent:
        kw = {"overlap": bool(overlap_with)} if "overlap" in inspect.signature(self.speakers.assign).parameters else {}
        track = self.speakers.assign(float(azimuth), start_ms, end_ms, audio, self.cfg.sample_rate,
                                     doa_conf if doa_conf is not None else 0.5, **kw)
        label, rebind = track.label, track.rebind_hint
        az_state = (
            Reliability.NEEDS_REVIEW
            if overlap_with or (doa_conf is not None and doa_conf < 0.3) else Reliability.USABLE
        )
        az_rec = SourceRecord(
            source_id=f"src_az_{seg_id}", kind="azimuth", value=round(float(azimuth), 1), unit="deg",
            reference="mic_pair_broadside", valid_from_ms=start_ms, valid_to_ms=end_ms,
            reliability_state=az_state, rebind_hint=rebind,
        )
        spk_rec = SourceRecord(
            source_id=f"src_{label}", kind="anon_speaker", value=label, unit="label", reference="session",
            valid_from_ms=start_ms, valid_to_ms=end_ms,
            reliability_state=most_conservative(
                Reliability.NEEDS_REVIEW if track.reliability == "usable" else track.reliability,
            ),
            rebind_hint=rebind,
        )
        pos_diag = {"doa_confidence": doa_conf, **({"tracking": track.diagnostics} if track.diagnostics else {})}
        if enrolled is not None:
            pos_diag["enrolled_match"] = enrolled  # 声纹注册匹配只是线索，身份由应用与教师确认
        return self._emit(
            event_type=EventType.SOURCE_POSITION, segment_id=seg_id, start_ms=start_ms, end_ms=end_ms,
            source_ref=[az_rec.source_id, spk_rec.source_id], sources=[az_rec, spk_rec], diagnostics=pos_diag,
        )

    # ---------- 状态 ----------
    def report_gap(self, start_ms: int, end_ms: int, reason: str) -> SpeechEvent:
        """标注一段已收到但不可用的音频（如采集端报告的损坏区间），时间轴不变。"""
        return self._emit(event_type=EventType.STREAM_STATUS, status="gap", gap=Gap(start_ms=start_ms, end_ms=end_ms, reason=reason))

    def mark_gap(self, duration_ms: int, reason: str = "stream_dropout") -> SpeechEvent:
        """断流：在当前位置补 duration_ms 的静音并记一条 gap 事件，之后的音频仍对齐真实时间。

        补的静音不进 VAD（否则噪声底被拉到 -100 dB），正在说的那句在断点处截止。
        """
        if self._seg_start is not None:
            self._finish_segment(self._samples)
        start = self._samples
        n = int(duration_ms * self.cfg.sample_rate / 1000)
        with self._raw_lock:
            self._raw.write(np.zeros((n, 2), np.float32))
        if self.capture_started_unix_ms is None:
            self.capture_started_unix_ms, self._clock_source = int(time.time() * 1000), "server_first_frame"
            self._write_timebase()
        self._samples += n
        self._buffer, self._buffer_start = np.zeros((2, 0), np.float32), self._samples
        self._seg_start, self._silence = None, 0
        return self.report_gap(self._ms(start), self._ms(self._samples), reason)

    def end(self, status: str = "completed") -> SpeechEvent:
        if self._seg_start is not None:
            self._finish_segment(self._samples)
        with self._raw_lock:
            self._raw.close()
        self.ended = True
        self._emit(event_type=EventType.AUDIO_AVAILABLE, audio_ref=[AudioRef(id=f"aud_{self.session_id}_raw", kind="raw")],
                   start_ms=0, end_ms=self._ms(self._samples))
        ev = self._emit(event_type=EventType.SESSION_ENDED, status=status, start_ms=0, end_ms=self._ms(self._samples))
        self._event_log.close()
        return ev
