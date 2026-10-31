"""阶段插槽：把四个优化方向接进同一条流水线，并保留基准实现作兜底与消融对照。

    定位 / 跟踪   localization.py   localize() + SpeakerTracker
    去噪         denoise_v2.py     adaptive_denoise()
    重叠分离      separation_v2.py  separate()
    数学转写守卫   math_asr.py       MathGuardedAsr

每个方向的模块缺失或导入失败时，退回基准实现并在 `Stages.origin` 里记下原因，
`/v1/capabilities` 与评测报告据此如实声明当前跑的是哪一版。
`Profile` 的开关用于逐项消融：只换一个阶段，看它单独带来的增益。
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field

import numpy as np

from .denoise import DenoiseConfig, dual_gate_denoise
from .separation import OverlapReport, selective_separate
from .spatial import ArrayConfig, estimate_sources, frame_energy_db, srp_phat

log = logging.getLogger(__name__)


# ---------- 统一数据结构（与 integrated/INTERFACE.md 一致） ----------
@dataclass
class LocalizationResult:
    azimuths: list[float]
    confidence: list[float]
    frame_azimuth: np.ndarray
    frame_confidence: np.ndarray


@dataclass
class TrackDecision:
    label: str
    rebind_hint: bool
    reliability: str = "needs_review"
    diagnostics: dict = field(default_factory=dict)


@dataclass
class GuardedResult:
    text: str | None
    engine: str
    reliability: str = "usable"
    review_reasons: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    math_terms: list[dict] = field(default_factory=list)


# ---------- 基准兜底 ----------
def baseline_localize(spec, cfg: ArrayConfig, noise_cross=None, max_sources: int = 2) -> LocalizationResult:
    az = sorted(estimate_sources(spec, cfg, max_sources=max_sources, noise_cross=noise_cross))
    grid = np.arange(-90, 91, 1.0)
    p = srp_phat(spec, cfg, grid, noise_cross=noise_cross)
    e = frame_energy_db(spec)
    frame_az = grid[np.argmax(p, axis=1)].astype(float)
    frame_az[e < np.percentile(e, 50)] = np.nan
    # 基准没有置信度概念：如实给 nan，下游按“未知”处理
    return LocalizationResult(az, [float("nan")] * len(az), frame_az, np.full(len(frame_az), np.nan))


class BaselineTracker:
    """基准 AnonymousSpeakers：按方位就近归并。"""

    def __init__(self, tolerance_deg: float = 15.0, drift_deg: float = 20.0) -> None:
        self.tracks: list[list] = []  # [label, azimuth, last_ms]
        self.tolerance, self.drift = tolerance_deg, drift_deg

    def assign(self, azimuth, start_ms, end_ms=None, audio=None, sample_rate=16000, confidence=None) -> TrackDecision:
        near = min(self.tracks, key=lambda t: abs(t[1] - azimuth), default=None)
        if near is not None and abs(near[1] - azimuth) <= self.tolerance:
            rebind = abs(near[1] - azimuth) > self.drift / 2 and start_ms - near[2] > 60_000
            near[1], near[2] = 0.8 * near[1] + 0.2 * azimuth, start_ms
            return TrackDecision(near[0], rebind)
        label = f"spk_{len(self.tracks) + 1:02d}"
        self.tracks.append([label, azimuth, start_ms])
        return TrackDecision(label, False)


def baseline_denoise(x, cfg, theta_deg=None, doa_confidence=None, noise_cross=None, noise_power=None):
    y, diag = dual_gate_denoise(x, cfg, DenoiseConfig(), theta_deg=theta_deg)
    diag["fallback_to_raw"] = diag["mean_gain"] <= 0.15  # 基准的质量门控
    return y, diag


def baseline_separate(x, azimuths, cfg, noise_cross=None, localization=None, enrollment=None):
    return selective_separate(x, azimuths, cfg, noise_cross=noise_cross)


class PassThroughGuard:
    """基准：直接用底层引擎结果，不做数学语义核查。"""

    def __init__(self, base) -> None:
        self.base = base
        self.name = getattr(base, "name", "none")

    def transcribe(self, audio, sample_rate, context=None) -> GuardedResult | None:
        if self.base is None:
            return None
        r = self.base.transcribe(audio, sample_rate)
        return None if r is None else GuardedResult(text=r.text, engine=r.engine)


def consensus(localize):
    """声源个数听基准、方位值听新方案。

    新方案的方位更准，但会把风扇这类持续噪声（反畸变曲线在 ±70° 饱和）报成第二声源，
    把单人片段送去分离、拖累音质。基准扣过噪声互谱，个数判断更稳。两者都认为有第二个
    声源时才保留；否则只留与基准方位最近的那个。
    """

    def wrapped(spec, cfg, noise_cross=None, max_sources=2):
        loc = localize(spec, cfg, noise_cross=noise_cross, max_sources=max_sources)
        if len(loc.azimuths) < 2:
            return loc
        ref = sorted(estimate_sources(spec, cfg, max_sources=max_sources, noise_cross=noise_cross))
        if len(ref) >= len(loc.azimuths):
            return loc
        keep = sorted({int(np.argmin([abs(a - r) for a in loc.azimuths])) for r in ref}) if ref else [int(np.argmax(loc.confidence))]
        return LocalizationResult([loc.azimuths[i] for i in keep], [loc.confidence[i] for i in keep], loc.frame_azimuth, loc.frame_confidence)

    wrapped.__wrapped__ = localize
    return wrapped


# ---------- 组装 ----------
@dataclass(frozen=True)
class Profile:
    """每个阶段用新方案（True）还是基准（False）。"""

    localization: bool = True
    tracking: bool = True
    denoise: bool = True
    separation: bool = True
    math_guard: bool = True
    refine_single: bool = True  # 分离分路后，单人区间改用去噪而不是分离掩码（整合层的联动优化）

    @classmethod
    def baseline(cls) -> "Profile":
        return cls(False, False, False, False, False, False)


def _try(module: str, attr: str):
    try:
        mod = importlib.import_module(f".{module}", __package__)
        return getattr(mod, attr), "contrib"
    except Exception as exc:  # noqa: BLE001 — 方向模块未交付或有错时退回基准
        log.info("%s.%s 不可用，用基准：%s", module, attr, exc)
        return None, f"baseline ({type(exc).__name__})"


@dataclass
class Stages:
    localize: object
    make_tracker: object
    denoise: object
    separate: object
    guard_cls: object
    origin: dict[str, str]


def build_stages(profile: Profile | None = None) -> Stages:
    profile = profile or Profile()
    origin: dict[str, str] = {}

    def pick(flag: bool, key: str, module: str, attr: str, fallback):
        if not flag:
            origin[key] = "baseline (profile)"
            return fallback
        fn, how = _try(module, attr)
        origin[key] = how
        return fn or fallback

    localize = pick(profile.localization, "localization", "localization", "localize", baseline_localize)
    if localize is not baseline_localize:
        localize = consensus(localize)
    return Stages(
        localize=localize,
        make_tracker=pick(profile.tracking, "tracking", "localization", "SpeakerTracker", BaselineTracker),
        denoise=pick(profile.denoise, "denoise", "denoise_v2", "adaptive_denoise", baseline_denoise),
        separate=pick(profile.separation, "separation", "separation_v2", "separate", baseline_separate),
        guard_cls=pick(profile.math_guard, "math_guard", "math_asr", "MathGuardedAsr", PassThroughGuard),
        origin=origin,
    )


def as_report(report) -> OverlapReport:
    """容忍方向三返回带额外字段的报告对象。"""
    return report if hasattr(report, "windows") else OverlapReport(windows=list(report))
