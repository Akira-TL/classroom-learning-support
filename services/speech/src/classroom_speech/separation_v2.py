"""方向三整合入口：重叠感知的选择性分离 v2（按 integrated/INTERFACE.md）。

- 有 enrollment（{label: 注册音频}）：走声纹注册的选择性多人分离（见 enrolled.py），
  先从注册池里认出此刻在说话的人，再只对重叠帧做“音色 × 方位”融合掩码分离。
  返回的每一路对应一个被认出的注册说话人，report.labels 给出对应标签。
- 没有 enrollment：退回基准 selective_separate（每个方位一路），并补上逐帧 frame_overlap。
"""

from __future__ import annotations

import hashlib

import numpy as np

from .enrolled import EnrollConfig, SpeakerProfile, enroll, enrolled_separate
from .separation import OverlapReport, SeparationConfig, selective_separate
from .spatial import ArrayConfig

_PROFILE_CACHE: dict[str, SpeakerProfile] = {}


def _profile(label: str, audio: np.ndarray, cfg: ArrayConfig) -> SpeakerProfile:
    key = label + hashlib.sha1(np.ascontiguousarray(audio, dtype=np.float32).tobytes()).hexdigest()
    if key not in _PROFILE_CACHE:
        _PROFILE_CACHE[key] = enroll(label, np.asarray(audio, dtype=np.float32), cfg, EnrollConfig(learn_iters=60))
    return _PROFILE_CACHE[key]


def _frame_overlap_from_windows(report: OverlapReport, n_frames: int, cfg: ArrayConfig) -> np.ndarray:
    fps = cfg.sample_rate / cfg.hop
    acc, cnt = np.zeros(n_frames), np.zeros(n_frames)
    for w in report.windows:
        a, b = int(w["start_ms"] / 1000 * fps), min(int(w["end_ms"] / 1000 * fps), n_frames)
        cnt[a:b] += 1
        acc[a:b] += float(w["overlap"])
    return acc / np.maximum(cnt, 1)


def _windows_from_frames(counts: np.ndarray, speech: np.ndarray, cfg: ArrayConfig, azimuths: list[float],
                         window_s: float = 0.5, hop_s: float = 0.25) -> list[dict]:
    fps = cfg.sample_rate / cfg.hop
    win, hop = int(window_s * fps), int(hop_s * fps)
    out = []
    for start in range(0, max(len(counts) - win, 1), hop):
        seg = slice(start, start + win)
        sp = bool(speech[seg].mean() > 0.3)
        ov = bool(sp and (counts[seg] >= 2).mean() > 0.5)
        out.append({"start_ms": int(start / fps * 1000), "end_ms": int((start + win) / fps * 1000), "speech": sp,
                    "overlap": ov, "azimuths": list(azimuths) if ov else []})
    return out


def separate(
    x: np.ndarray,
    azimuths: list[float],
    cfg: ArrayConfig,
    noise_cross: np.ndarray | None = None,
    localization=None,
    enrollment: dict[str, np.ndarray] | None = None,
    noise_ref: np.ndarray | None = None,
) -> tuple[np.ndarray, OverlapReport]:
    """x: (2, N)。返回 ((K, N), report)；report 额外带 frame_overlap、stream_azimuths、stream_labels、gains。

    有注册时 K 为认出的人数，可多于 len(azimuths)；注册标签只是候选，身份确认由应用和教师完成。"""
    if enrollment:
        profiles = [_profile(label, audio, cfg) for label, audio in enrollment.items()]
        streams, active, rep = enrolled_separate(x, profiles, cfg, noise_ref=noise_ref)
        counts = rep.frame_counts
        speech = counts > 0
        azs = [profiles[i].azimuth_deg for i in active]
        report = OverlapReport(windows=_windows_from_frames(counts, speech, cfg, [a for a in azs if a is not None]))
        report.frame_overlap = (counts >= 2).astype(float)  # type: ignore[attr-defined]
        report.labels = [profiles[i].speaker_id for i in active]  # type: ignore[attr-defined]
        report.stream_azimuths = [float("nan") if a is None else float(a) for a in azs]  # type: ignore[attr-defined]
        report.stream_labels = [profiles[i].speaker_id for i in active]  # type: ignore[attr-defined]
        report.gains = rep.gains  # type: ignore[attr-defined]
        report.separated_ratio = rep.separated_ratio  # type: ignore[attr-defined]
        return streams, report
    streams, report = selective_separate(x, sorted(azimuths), cfg, SeparationConfig(), noise_cross)
    n_frames = 1 + x.shape[-1] // cfg.hop
    report.frame_overlap = _frame_overlap_from_windows(report, n_frames, cfg)  # type: ignore[attr-defined]
    order = np.argsort(np.argsort(azimuths))
    report.stream_azimuths = [float(a) for a in azimuths]  # type: ignore[attr-defined]
    report.stream_labels = [None] * len(azimuths)  # type: ignore[attr-defined]
    return streams[order], report
