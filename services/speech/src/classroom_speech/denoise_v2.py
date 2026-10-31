"""方向二：三证会审门控（Tri-Evidence Gate, TEG）——自适应空间—频谱联合去噪。

基准双门控 G = G_spec · M_sp^(1−G_spec) 让空间门的话语权只取决于频谱增益。本模块把
“空间门该说多少话”拆成三份独立证据，并让噪声估计锚定在会话的噪声指纹上：

    G(t,f) = max( G_spec · M_sp ^ α(t,f), floor )
    α(t,f) = A(噪声强度) · U(频谱门拿不准的程度) · C(方向可信度)

1. 噪声强度 —— 噪声指纹锚定：语音开始前的静音段给出 mic0 的噪声功率谱，作为最小值
   统计噪声估计的下限。最小值统计在语音持续时系统性低估噪声，这正是基准在 0 dB 下
   “空间门看起来有用”的真实原因：空间门在替噪声估计补漏。锚定后再用估计信噪比 A 决定
   空间门的基础权重。
2. 频谱不确定度 U：频谱门已经压到底或很有把握时空间门少说话，只在中间地带投票。
3. 方向可信度 C = 外部定位置信度 × 空间门自检：空间门对语音主导时频点的能量放行率
   应明显高于对噪声帧的放行率；拉不开（方位估错、噪声与人同向）就自动退场。
4. 语音保真护栏：噪声指纹不得高于本段最安静帧实测功率的 guard 倍——风扇关了、换了
   教室，旧指纹会过估噪声、吃掉轻声回答，这里直接截断。

所有证据都写进 diag，评委和老师能看到“这一段为什么这样处理”。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .denoise import DenoiseConfig, noise_psd_min_stats, spatial_mask, target_direction, wiener_gain
from .spatial import ArrayConfig, frame_energy_db, from_stft, to_stft


@dataclass(frozen=True)
class TriGateConfig:
    base: DenoiseConfig = field(default_factory=DenoiseConfig)
    anchor_noise: bool = True  # 噪声指纹锚定（消融时关掉）
    print_guard: float = 2.0  # 指纹最多为本段最安静帧功率的几倍
    quiet_pct: float = 20.0  # 本段“最安静帧”的分位数
    a_max: float = 1.0  # 极吵时空间门指数上限
    a_min: float = 0.0  # 安静时的下限
    snr_mid_db: float = -6.0  # A 的 logistic 中点（估计信噪比）
    snr_width_db: float = 2.5
    u_low: float = 0.08  # G_spec 低于此视为已判噪声
    u_rise: float = 0.25  # G_spec 升到此时空间门完全参与
    u_high_keep: float = 0.4  # G_spec→1 时保留的空间门权重
    ratio_bad: float = 1.6  # 自检放行比低于此值：空间门分不清人和噪声，完全退场
    ratio_ok: float = 2.4  # 高于此值：方向完全可信
    self_check: bool = True  # 消融时关掉


def anchored_noise_psd(
    power: np.ndarray,
    quiet: np.ndarray,
    cfg: ArrayConfig,
    tcfg: TriGateConfig,
    noise_power: np.ndarray | None,
    noise_cross: np.ndarray | None = None,
) -> tuple[np.ndarray, dict]:
    """最小值统计 ∨ 噪声指纹（带保真护栏）。返回 (freqs, frames) 噪声功率与诊断。

    指纹来源优先级：mic0 静音功率谱 noise_power ＞ 静音互谱幅度 |noise_cross|
    （≤ mic0 噪声功率，弥散噪声时偏小，只会少压不会多压）＞ 本段最安静帧。
    """
    tracked = noise_psd_min_stats(power, cfg, tcfg.base)
    if not tcfg.anchor_noise:
        return tracked, {"noise_source": "min_stats"}
    local = power[:, quiet].mean(axis=1)
    if noise_power is None and noise_cross is None:
        anchor, source, clipped = local, "segment_quiet_frames", 0.0
    else:
        fp = noise_power if noise_power is not None else np.abs(noise_cross)
        cap = tcfg.print_guard * local
        anchor = np.minimum(fp, cap)
        source = "session_noise_print" if noise_power is not None else "session_noise_cross"
        clipped = float(np.mean(fp > cap))
    return np.maximum(tracked, anchor[:, None]), {"noise_source": source, "print_clipped_ratio": round(clipped, 3)}


def estimate_snr_db(power: np.ndarray, noise: np.ndarray) -> float:
    sig = np.maximum(power.mean(axis=1) - noise.mean(axis=1), 1e-12).sum()
    return float(10 * np.log10(sig / (noise.mean(axis=1).sum() + 1e-12)))


def spectral_uncertainty(g: np.ndarray, tcfg: TriGateConfig) -> np.ndarray:
    rise = np.clip((g - tcfg.u_low) / (tcfg.u_rise - tcfg.u_low), 0, 1)
    fall = 1 - (1 - tcfg.u_high_keep) * np.clip((g - 0.7) / 0.3, 0, 1)
    return rise * fall


def direction_self_check(
    m: np.ndarray, g: np.ndarray, power: np.ndarray, energy_db: np.ndarray, quiet: np.ndarray, cfg: ArrayConfig
) -> dict:
    """空间门自检：语音主导时频点的能量放行率 ÷ 噪声帧的能量放行率（200–4000 Hz）。

    仿真里方位正确、噪声与人分得开时约 2.5–3；方位偏 35° 或噪声与人同向时降到 1.5 左右。
    """
    band = ((cfg.freqs > 200) & (cfg.freqs < 4000))[:, None]
    noise_bins = band & quiet[None]
    speech_bins = band & (g > 0.5) & (energy_db > np.percentile(energy_db, 60))[None]
    noise_pass = float((m * power)[noise_bins].sum() / (power[noise_bins].sum() + 1e-12))
    if speech_bins.sum() < 20:
        return {"noise_pass": round(noise_pass, 3), "speech_pass": None, "ratio": 1.0}
    speech_pass = float((m * power)[speech_bins].sum() / (power[speech_bins].sum() + 1e-12))
    return {"noise_pass": round(noise_pass, 3), "speech_pass": round(speech_pass, 3), "ratio": speech_pass / max(noise_pass, 1e-3)}


def adaptive_denoise(
    x: np.ndarray,
    cfg: ArrayConfig,
    theta_deg: float | None = None,
    doa_confidence: float | None = None,
    noise_cross: np.ndarray | None = None,
    noise_power: np.ndarray | None = None,
    tcfg: TriGateConfig | None = None,
) -> tuple[np.ndarray, dict]:
    """三证会审门控。x: (2, N) → ((N,), diag)。

    noise_power：会话噪声指纹里 mic0 的平均功率谱 (freqs,)，由流水线在静音段维护；
    没有时退而用静音互谱 noise_cross 的幅度，再没有就用本段最安静帧。
    """
    tcfg = tcfg or TriGateConfig()
    d = tcfg.base
    if x.ndim != 2 or x.shape[0] < 2 or x.shape[1] < cfg.n_fft or not np.isfinite(x).all():
        y = np.nan_to_num(x[0] if x.ndim == 2 else x).astype(np.float32)
        return y, {"target_azimuth_deg": theta_deg, "mean_gain": 1.0, "fallback_to_raw": True, "reason": "输入过短或无效"}
    spec = to_stft(x, cfg)
    theta = target_direction(spec, cfg) if theta_deg is None else float(theta_deg)
    ref = spec[0]
    power = np.abs(ref) ** 2
    energy = frame_energy_db(spec)
    quiet = energy <= np.percentile(energy, tcfg.quiet_pct)

    noise, noise_diag = anchored_noise_psd(power, quiet, cfg, tcfg, noise_power, noise_cross)
    g = wiener_gain(ref, noise, d)
    snr = estimate_snr_db(power, noise)
    a = tcfg.a_min + (tcfg.a_max - tcfg.a_min) / (1 + np.exp((snr - tcfg.snr_mid_db) / tcfg.snr_width_db))

    m = spatial_mask(spec, theta, cfg, d)
    check = direction_self_check(m, g, power, energy, quiet, cfg)
    c_self = float(np.clip((check["ratio"] - tcfg.ratio_bad) / (tcfg.ratio_ok - tcfg.ratio_bad), 0, 1)) if tcfg.self_check else 1.0
    c = c_self if doa_confidence is None else c_self * float(np.clip(doa_confidence, 0, 1))
    alpha = (a * c) * spectral_uncertainty(g, tcfg)

    gain = np.maximum(g * m**alpha, d.gain_floor)
    y = from_stft(ref * gain, cfg, x.shape[-1])
    weight = float(a * c)
    return y, {
        "target_azimuth_deg": theta,
        "mean_gain": float(gain.mean()),
        "fallback_to_raw": False,
        "snr_est_db": round(snr, 2),
        "noise_weight": round(float(a), 3),
        "direction_confidence": round(c, 3),
        "self_check": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in check.items()},
        "spatial_gate": "on" if weight > 0.3 else ("weak" if weight > 0.05 else "off"),
        "spatial_weight": round(weight, 3),
        **noise_diag,
    }
