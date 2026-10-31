"""方向一：混响鲁棒的方位估计 + 方位 × 声纹联合的匿名说话人跟踪。

为什么基准在混响里会偏：双麦线阵只能测“声音从哪个锥面来”。教室里黑板墙、地板、
天花板的反射像一圈“镜像学生”，它们的锥面都比真实方向更靠近正前方；混响能量又
比直达声大好几倍（8×6×3 m、RT60 0.45 s 的临界距离只有约 1 m），于是方位被系统性
地“压”向 0°：75° 的学生会被测成 40° 左右。这里分三步把它纠回来：

1. 起音加权（优先效应）：人耳靠“第一声”定位，后来的回声被大脑忽略。每个时频点
   如果能量比前几帧明显上升，说明直达声刚到、回声还没跟上，给它更大的投票权。
2. 扩散场补偿：近距双麦上，扩散混响的相干函数是实数 sinc(kd)，相当于一个永远站在
   正前方的“幽灵声源”。逐个时频点解出混响占比 α，从相干函数里减掉 α·sinc(kd)
   再取相位；直达占比 1−α 同时作为该点的可信度。
3. 数字孪生反畸变：剩下的偏差由房间几何决定，是可预测的。安装时填写教室尺寸与
   阵列位置，用镜像法仿真一间“虚拟教室”，让虚拟学生在各个方向说话，学到
   “测得方位 → 真实方位”的单调曲线（仿真时把尺寸、阵列位置、嘴高、RT60 都在
   测量误差范围内抖动，曲线因此对填错几十厘米不敏感），推理时查表反扭回去。

跟踪：座位会变，嗓音不会；嗓音会像，座位不同。`SpeakerTracker` 把两种证据各自换算成
“是同一人”的对数似然比再相加：
- 方位证据：差距按方位置信度放宽，且有下限——“不太可能”不等于“不可能”，留给换座。
- 声纹证据：基频（对房间不敏感）+ 谱包络形状。
同方向但嗓音明显不同 → 新标签（邻座/前后排）；方向变了但嗓音强匹配 → 沿用标签并给
rebind_hint（换座）。两种证据冲突时标 needs_review，交给教师端确认，不擅自定论。
标签只在会话内有效，不代表真实身份。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import uniform_filter, uniform_filter1d

from .spatial import SPEED_OF_SOUND, ArrayConfig, find_peaks_1d, frame_energy_db, tdoa

try:  # 整合包里与 stages 共用数据结构；单独使用时退回本地定义（字段一致）
    from .stages import LocalizationResult, TrackDecision
except Exception:  # noqa: BLE001

    @dataclass
    class LocalizationResult:  # type: ignore[no-redef]
        azimuths: list[float]
        confidence: list[float]
        frame_azimuth: np.ndarray
        frame_confidence: np.ndarray

    @dataclass
    class TrackDecision:  # type: ignore[no-redef]
        label: str
        rebind_hint: bool
        reliability: str = "needs_review"
        diagnostics: dict = field(default_factory=dict)


GRID = np.arange(-90, 91, 1.0)

# 标称教室（8×6×3 m，阵列在前方中央、离黑板墙 1 m、高 1.2 m，RT60 0.3–0.9 s）的孪生反畸变曲线：
# 测得 |方位| → 真实 |方位|。由 bench_localization.py calibrate 生成（调参种子 1，240 个虚拟发言）。
# 换教室时用同一命令按实际尺寸重新生成，传给 localize(dewarp=...)。
DEFAULT_DEWARP = (
    (0.0, 2.5, 5.0, 7.5, 10.0, 12.5, 15.0, 17.5, 20.0, 22.5, 25.0, 27.5, 30.0, 32.5, 35.0, 37.5, 40.0, 42.5, 45.0,
     47.5, 50.0, 52.5, 55.0, 57.5, 60.0, 62.5, 65.0, 67.5, 70.0, 72.5, 75.0, 77.5, 80.0, 82.5, 85.0, 87.5, 90.0),
    None,  # 由 _DEFAULT_TRUE 填充，见文件末尾
)


@dataclass(frozen=True)
class LocalizationConfig:
    fmin: float = 100.0
    fmax: float = 4000.0
    tsmooth: int = 4  # 互谱时间平滑帧数（32 ms）
    onset_lookback: int = 6
    onset_thr_db: float = 3.0
    onset_floor: float = 0.1  # 非起音点保留的投票权
    active_quantile: float = 50.0
    min_sep_deg: float = 12.0
    rel: float = 0.25
    vote_smooth: int = 5


# ---------- 时频特征 ----------
def _smooth_c(z: np.ndarray, t: int) -> np.ndarray:
    return uniform_filter(z.real, (1, t)) + 1j * uniform_filter(z.imag, (1, t))


def onset_weight(spec: np.ndarray, lookback: int = 6, thr_db: float = 3.0) -> np.ndarray:
    """优先效应：时频点能量相对前 lookback 帧均值上升超过 thr_db，视为直达声刚到。返回 0~1。"""
    p = np.abs(spec[0]) ** 2
    prev = uniform_filter1d(p, lookback, axis=1, origin=(lookback - 1) // 2)
    prev = np.concatenate([np.full((p.shape[0], 1), np.inf), prev[:, :-1]], axis=1)
    rise = 10 * np.log10(p / (prev + 1e-12) + 1e-12)
    return np.clip((rise - thr_db) / 6.0, 0.0, 1.0)


def diffuse_compensate(c: np.ndarray, p0: np.ndarray, p1: np.ndarray, cfg: ArrayConfig) -> tuple[np.ndarray, np.ndarray]:
    """扩散场补偿。相干 γx ≈ (1−α)·e^{−jωτ} + α·γn，γn = sinc(kd) 为实数。
    由 |γx − α·γn| = 1 − α 解 α（取 [0,1] 内较小根），返回 (直达声单位相位, 直达占比 1−α)。"""
    n = np.sinc(2 * cfg.freqs[:, None] * cfg.mic_distance_m / SPEED_OF_SOUND) * np.ones_like(p0)
    g = c / np.sqrt(p0 * p1 + 1e-20)
    a, b, cc = n**2 - 1, 2 - 2 * n * g.real, np.abs(g) ** 2 - 1
    disc = np.sqrt(np.maximum(b**2 - 4 * a * cc, 0))
    with np.errstate(divide="ignore", invalid="ignore"):
        roots = np.stack([(-b + disc) / (2 * a), (-b - disc) / (2 * a)])
    roots = np.where((roots >= 0) & (roots <= 1), roots, np.inf)
    alpha = np.min(roots, axis=0)
    alpha = np.clip(np.where(np.isfinite(alpha), alpha, 0.0), 0, 1)
    d = g - alpha * n
    return d / (np.abs(d) + 1e-12), 1 - alpha


def _noise_psd(spec: np.ndarray, quantile: float = 25) -> np.ndarray:
    e = frame_energy_db(spec)
    quiet = e <= np.percentile(e, quantile)
    return np.mean(np.abs(spec[:, :, quiet]) ** 2, axis=2)


def robust_spatial_map(
    spec: np.ndarray, cfg: ArrayConfig, noise_cross: np.ndarray | None = None, noise_psd: np.ndarray | None = None,
    lcfg: LocalizationConfig | None = None,
) -> np.ndarray:
    """逐帧空间谱 (frames, len(GRID))：去持续噪声互谱 → 扩散场补偿 → 直达占比 × 起音权重加权的 SRP。"""
    lcfg = lcfg or LocalizationConfig()
    f = cfg.freqs
    band = (f > lcfg.fmin) & (f < lcfg.fmax)
    x0, x1 = spec[0], spec[1]
    c = _smooth_c(x1 * np.conj(x0), lcfg.tsmooth)
    if noise_cross is not None:
        c = c - noise_cross[:, None]
    p0 = uniform_filter1d(np.abs(x0) ** 2, lcfg.tsmooth, axis=1)
    p1 = uniform_filter1d(np.abs(x1) ** 2, lcfg.tsmooth, axis=1)
    npsd = _noise_psd(spec) if noise_psd is None else noise_psd
    p0 = np.maximum(p0 - npsd[0][:, None], 1e-3 * p0)
    p1 = np.maximum(p1 - npsd[1][:, None], 1e-3 * p1)
    u, direct = diffuse_compensate(c, p0, p1, cfg)
    w = direct * (lcfg.onset_floor + onset_weight(spec, lcfg.onset_lookback, lcfg.onset_thr_db))
    expected = np.exp(-1j * np.outer(tdoa(GRID, cfg), 2 * np.pi * f[band]))
    return np.real(expected.conj() @ (u[band] * w[band])).T / band.sum()


# ---------- 孪生反畸变 ----------
@dataclass(frozen=True)
class DewarpCurve:
    """测得 |方位| → 真实 |方位| 的单调曲线（左右对称教室）。slope 用来给置信度打折：曲线越平，越难分辨。"""

    measured: tuple[float, ...]
    true: tuple[float, ...]

    def __call__(self, az: float | np.ndarray) -> np.ndarray:
        a = np.asarray(az, float)
        return np.sign(a) * np.interp(np.abs(a), self.measured, self.true)

    def gain(self, az: float) -> float:
        """局部放大倍数 d真实/d测得：>2 说明此处测量 1° 误差会放大成 2° 以上。"""
        m, t = np.asarray(self.measured), np.asarray(self.true)
        k = int(np.clip(np.searchsorted(m, abs(az)), 1, len(m) - 1))
        return float((t[k] - t[k - 1]) / (m[k] - m[k - 1] + 1e-9))

    @classmethod
    def fit(cls, measured: np.ndarray, true: np.ndarray, bw: float = 6.0) -> "DewarpCurve":
        """核回归 + 单调化。输入为孪生里虚拟发言的 (测得方位, 真实方位) 对。"""
        m = np.concatenate([measured, -measured])
        t = np.concatenate([true, -true])
        ok = np.isfinite(m)
        m, t = m[ok], t[ok]
        knots = np.arange(0, 90.1, 2.5)
        y = []
        for k in knots:
            w = np.exp(-0.5 * ((m - k) / bw) ** 2)
            y.append(np.sum(w * t) / w.sum() if w.sum() > 0.5 else np.nan)
        y = np.asarray(y)
        good = np.isfinite(y)
        y = np.interp(knots, knots[good], y[good])
        y[0] = 0.0
        y = np.maximum.accumulate(np.clip(y, 0, 90))
        return cls(tuple(knots.tolist()), tuple(np.round(y, 2).tolist()))


def default_dewarp() -> DewarpCurve:
    return DewarpCurve(DEFAULT_DEWARP[0], _DEFAULT_TRUE)


IDENTITY = DewarpCurve((0.0, 90.0), (0.0, 90.0))


# ---------- 对外接口 ----------
def localize(
    spec: np.ndarray, cfg: ArrayConfig, noise_cross: np.ndarray | None = None, max_sources: int = 2,
    noise_psd: np.ndarray | None = None, dewarp: DewarpCurve | None = None, lcfg: LocalizationConfig | None = None,
) -> LocalizationResult:
    """估计一段音频的声源方位与置信度。dewarp=IDENTITY 可关掉孪生反畸变（消融用）。"""
    lcfg = lcfg or LocalizationConfig()
    curve = default_dewarp() if dewarp is None else dewarp
    p = robust_spatial_map(spec, cfg, noise_cross, noise_psd, lcfg)
    e = frame_energy_db(spec)
    active = e > np.percentile(e, lcfg.active_quantile)
    idx = np.argmax(p, axis=1)
    peak = p[np.arange(len(p)), idx]
    # 逐帧置信度：峰值相对整帧空间谱的突出程度（0~1），无语音帧为 0
    spread = p.mean(axis=1)
    frame_conf = np.clip((peak - spread) / (np.abs(peak) + np.abs(spread) + 1e-9), 0, 1) * active
    votes = np.bincount(idx[active], minlength=len(GRID)).astype(float)
    votes = np.convolve(votes, np.ones(lcfg.vote_smooth) / lcfg.vote_smooth, mode="same")
    measured = find_peaks_1d(votes, GRID, max_sources, lcfg.min_sep_deg, lcfg.rel) if active.any() else []
    azimuths, conf = [], []
    total = votes.sum() + 1e-9
    for m in measured:
        near = np.abs(GRID - m) <= 6
        share = votes[near].sum() / total  # 该方位得票占比
        frames = active & (np.abs(GRID[idx] - m) <= 6)
        sharp = float(np.mean(frame_conf[frames])) if frames.any() else 0.0
        # 曲线平的地方（靠近端射方向）测量误差会被放大，置信度相应打折
        c = np.clip(1.6 * share, 0, 1) ** 0.5 * np.clip(sharp * 2, 0, 1) / max(1.0, curve.gain(m) / 1.5)
        azimuths.append(float(np.round(curve(m), 1)))
        conf.append(round(float(np.clip(c, 0, 1)), 3))
    order = np.argsort(azimuths)
    frame_az = curve(GRID[idx]).astype(float)
    frame_az[~active] = np.nan
    return LocalizationResult([azimuths[i] for i in order], [conf[i] for i in order], frame_az, frame_conf.astype(float))


# ---------- 声纹 ----------
def _mel_fb(sr: int, n_fft: int, n_mels: int = 32, fmin: float = 80, fmax: float = 7000) -> np.ndarray:
    mel = lambda f: 2595 * np.log10(1 + f / 700)  # noqa: E731
    imel = lambda m: 700 * (10 ** (m / 2595) - 1)  # noqa: E731
    pts = imel(np.linspace(mel(fmin), mel(fmax), n_mels + 2))
    f = np.fft.rfftfreq(n_fft, 1 / sr)
    fb = np.zeros((n_mels, len(f)))
    for i in range(n_mels):
        lo, c, hi = pts[i : i + 3]
        fb[i] = np.clip(np.minimum((f - lo) / (c - lo), (hi - f) / (hi - c)), 0, None)
    return fb


def _pitch_track(y: np.ndarray, sr: int, frame: int = 640, hop: int = 160, fmin: float = 70, fmax: float = 450) -> np.ndarray:
    """归一化自相关基频，清音/静音帧返回 nan。"""
    out = []
    lo, hi = int(sr / fmax), int(sr / fmin)
    for s in range(0, len(y) - frame, hop):
        w = y[s : s + frame] * np.hanning(frame)
        if np.sqrt(np.mean(w**2)) < 1e-4:
            out.append(np.nan)
            continue
        r = np.correlate(w, w, "full")[frame - 1 :]
        r = r / (r[0] + 1e-12)
        seg = r[lo:hi]
        best = float(seg.max())
        # 防倍频错误：取第一个达到最高峰 90% 的局部峰（周期的整数倍处也有峰，最短的才是基频）
        peaks = np.where((seg[1:-1] >= seg[:-2]) & (seg[1:-1] >= seg[2:]) & (seg[1:-1] >= 0.9 * best))[0]
        k = lo + 1 + int(peaks[0]) if len(peaks) else lo + int(np.argmax(seg))
        out.append(sr / k if best > 0.5 else np.nan)
    return np.asarray(out)


@dataclass
class VoicePrint:
    f0_semitone: float  # 中位基频（相对 100 Hz 的半音数）；nan 表示没测到浊音
    envelope: np.ndarray  # 去均值的对数梅尔谱包络（形状，不含响度）
    voiced_s: float

    def distance(self, other: "VoicePrint") -> tuple[float | None, float]:
        """返回 (基频差 半音, 包络余弦距离)。"""
        df = None if np.isnan(self.f0_semitone) or np.isnan(other.f0_semitone) else abs(self.f0_semitone - other.f0_semitone)
        a, b = self.envelope, other.envelope
        cos = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
        return df, 1 - cos


def voice_print(audio: np.ndarray, sample_rate: int) -> VoicePrint | None:
    y = np.asarray(audio, float)
    if y.ndim > 1:
        y = y[0]
    if len(y) < sample_rate * 0.3:
        return None
    f0 = _pitch_track(y, sample_rate)
    voiced = f0[np.isfinite(f0)]
    n_fft, hop = 512, 160
    frames = np.lib.stride_tricks.sliding_window_view(y, n_fft)[::hop] * np.hanning(n_fft)
    pw = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    logmel = np.log(pw @ _mel_fb(sample_rate, n_fft).T + 1e-10)
    e = logmel.mean(axis=1)
    loud = e > np.percentile(e, 60)
    env = logmel[loud].mean(axis=0)
    env = env - env.mean()
    st = float(np.median(12 * np.log2(voiced / 100))) if len(voiced) >= 5 else float("nan")
    return VoicePrint(st, env, len(voiced) * 0.01)


# ---------- 跟踪 ----------
@dataclass
class TrackerConfig:
    az_sigma_deg: float = 9.0  # 置信度为 1 时同一人方位抖动
    az_sigma_lowconf_deg: float = 25.0
    az_llr_floor: float = -2.5  # 方位再远也只扣这么多：人会换座，“不太可能”不等于“不可能”
    # 声纹似然模型（在调参种子 0 的合成课堂上统计同人/异人距离分布得到）
    f0_same_sigma: float = 0.4  # 同一人基频差（半音）主体
    f0_same_outlier: float = 0.15  # 同一人也偶有基频跟踪出错（倍频/半频），给 15% 均匀尾部
    f0_diff_scale: float = 7.0  # 不同人基频差 ~ 指数分布
    env_same_scale: float = 0.03  # 包络余弦距离：同人 ~ Exp(0.03)，异人 ~ Exp(0.12)
    env_diff_scale: float = 0.12
    new_threshold: float = 0.5  # 合并 LLR 低于此值就开新标签
    review_margin: float = 2.0  # 证据冲突且合并 LLR 不到阈值 + 此值时标 needs_review
    rebind_deg: float = 25.0
    rebind_voice_llr: float = 2.0  # 新开标签时，若嗓音对某已有标签的 LLR 超过此值，给出换座提示
    max_tracks: int = 40


@dataclass
class _Track:
    label: str
    azimuth: float
    last_ms: int
    f0: float = float("nan")
    env: np.ndarray | None = None
    n: int = 0
    history: list = field(default_factory=list)


class SpeakerTracker:
    """方位 × 声纹联合的会话内匿名说话人跟踪。"""

    def __init__(self, cfg: TrackerConfig | None = None) -> None:
        self.cfg = cfg or TrackerConfig()
        self.tracks: list[_Track] = []

    # 各项对数似然比：>0 支持“同一人”，<0 支持“不同人”
    def _llr_space(self, t: _Track, az: float, conf: float) -> float:
        c = self.cfg
        conf = 0.5 if conf is None or not np.isfinite(conf) else float(np.clip(conf, 0, 1))
        sigma = c.az_sigma_deg + (1 - conf) * (c.az_sigma_lowconf_deg - c.az_sigma_deg)
        d = abs(t.azimuth - az)
        # 同一人：N(0, σ)；不同人：在 ±90° 内均匀
        llr = -0.5 * (d / sigma) ** 2 - np.log(sigma * np.sqrt(2 * np.pi)) + np.log(180)
        return float(max(llr, c.az_llr_floor))

    def _llr_voice(self, t: _Track, vp: VoicePrint | None) -> float | None:
        if vp is None or t.env is None:
            return None
        c = self.cfg
        df, de = VoicePrint(t.f0, t.env, 0).distance(vp)
        llr = 0.0
        if df is not None:
            same = (1 - c.f0_same_outlier) * np.exp(-0.5 * (df / c.f0_same_sigma) ** 2) / (c.f0_same_sigma * np.sqrt(np.pi / 2)) \
                + c.f0_same_outlier / 15.0
            diff = np.exp(-df / c.f0_diff_scale) / c.f0_diff_scale
            llr += np.log(same / diff)
        llr += np.log(c.env_diff_scale / c.env_same_scale) - de * (1 / c.env_same_scale - 1 / c.env_diff_scale)
        return float(np.clip(llr, -12, 8))

    def assign(self, azimuth: float, start_ms: int, end_ms: int | None = None, audio: np.ndarray | None = None,
               sample_rate: int = 16000, confidence: float | None = None) -> TrackDecision:
        vp = voice_print(audio, sample_rate) if audio is not None else None
        scored = []
        for t in self.tracks:
            ls, lv = self._llr_space(t, azimuth, confidence), self._llr_voice(t, vp)
            scored.append((ls + (lv if lv is not None else 0.0), ls, lv, t))
        best = max(scored, key=lambda s: s[0], default=None)
        diag: dict = {"voice_f0_semitone": None if vp is None else round(vp.f0_semitone, 2), "candidates": [
            {"label": s[3].label, "llr": round(s[0], 2), "llr_space": round(s[1], 2), "llr_voice": None if s[2] is None else round(s[2], 2)}
            for s in sorted(scored, key=lambda s: -s[0])[:3]]}
        if best is None or best[0] < self.cfg.new_threshold or len(self.tracks) >= self.cfg.max_tracks and best[0] < 0:
            t = _Track(f"spk_{len(self.tracks) + 1:02d}", azimuth, start_ms)
            self._update(t, azimuth, start_ms, vp)
            self.tracks.append(t)
            # 同方向有人但嗓音不同：明确说出“邻座/前后排”的判断依据
            same_dir = best is not None and best[1] > 1.0 and best[2] is not None and best[2] < -2
            diag["reason"] = "same_direction_different_voice" if same_dir else "new_direction"
            # 嗓音强匹配某个已有标签、只是方向变了：不擅自合并，提示“可能是换座的 spk_xx”，交给教师端一键确认
            voiced = [s for s in scored if s[2] is not None and s[2] >= self.cfg.rebind_voice_llr]
            if voiced:
                cand = max(voiced, key=lambda s: s[2])
                diag["possible_rebind_of"] = cand[3].label
                diag["reason"] = "voice_match_elsewhere"
            conflict = best is not None and best[0] > self.cfg.new_threshold - self.cfg.review_margin
            review = conflict or vp is None or bool(voiced)
            return TrackDecision(t.label, bool(voiced), "needs_review" if review else "usable", diag)
        total, ls, lv, t = best
        moved = abs(t.azimuth - azimuth) > self.cfg.rebind_deg
        conflict = (ls < 0 < (lv or 0)) or (lv is not None and lv < 0 < ls)
        diag["reason"] = "seat_change_voice_match" if moved else "consistent"
        self._update(t, azimuth, start_ms, vp, moved)
        reliability = "needs_review" if (conflict and total < self.cfg.new_threshold + self.cfg.review_margin) or lv is None else "usable"
        return TrackDecision(t.label, moved, reliability, diag)

    @staticmethod
    def _update(t: _Track, azimuth: float, now_ms: int, vp: VoicePrint | None, moved: bool = False) -> None:
        t.azimuth = azimuth if moved or t.n == 0 else 0.7 * t.azimuth + 0.3 * azimuth
        t.last_ms = now_ms
        if vp is not None:
            k = min(t.n, 4)
            if np.isfinite(vp.f0_semitone):
                t.f0 = vp.f0_semitone if not np.isfinite(t.f0) else (k * t.f0 + vp.f0_semitone) / (k + 1)
            t.env = vp.envelope.copy() if t.env is None else (k * t.env + vp.envelope) / (k + 1)
        t.n += 1
        t.history.append((now_ms, round(float(azimuth), 1)))


_DEFAULT_TRUE: tuple[float, ...] = (
    0.0, 4.15, 7.76, 10.77, 13.45, 16.15, 19.08, 22.3, 25.87, 29.87, 34.21, 38.54, 42.46, 45.78, 48.65, 51.32, 53.93, 56.42,
    58.62, 60.43, 61.88, 63.11, 64.29, 65.51, 66.8, 68.11, 69.29, 69.93, 69.93, 69.93, 69.93, 69.93, 69.93, 69.93, 69.93,
    69.93, 69.93,
)
