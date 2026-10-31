"""创新点 1：空间—频谱双门控去噪（Spatial-Spectral Dual Gate, SSDG）。

思路：单通道去噪只能看“这个频点的能量像不像噪声”，对风扇、投影仪、
走廊谈话这类与语音频谱重叠的声音区分有限。双通道多了一条信息：这个
时频点的相位差是否与说话人方向一致。两道门相乘：

    G(t,f) = G_spec(t,f) · M_spatial(t,f) ^ (1 − G_spec(t,f))

- G_spec：最小值统计估计噪声底 + 判决引导 Wiener 增益（经典做法，作为基线）。
- M_spatial：观测相位差与目标方位预期相位差的一致度，经时频平滑后取幂。
- 信噪比自适应指数 (1 − G_spec)：频谱门已判定为高信噪比的时频点几乎不再
  受空间门影响，避免方位估计偏差和混响损伤清晰语音；低信噪比时频点由空间门
  主导，压掉方向不对的噪声。这是本方案与简单相乘的关键区别。
- 目标方位：噪声互谱相减的 SRP-PHAT（见 target_direction）。

增益作用在参考麦克风 mic0 上，保持与原音频同一时间轴，可再接神经去噪模型。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import minimum_filter1d, uniform_filter, uniform_filter1d

from .spatial import (
    ArrayConfig,
    delay_and_sum,
    frame_energy_db,
    from_stft,
    steering,
    tdoa,
    to_stft,
)


@dataclass(frozen=True)
class DenoiseConfig:
    spatial_power: float = 3.0
    spatial_floor: float = 0.08
    gain_floor: float = 0.06
    min_window_s: float = 1.5
    noise_bias: float = 1.6
    dd_alpha: float = 0.96


def noise_psd_min_stats(power: np.ndarray, cfg: ArrayConfig, dcfg: DenoiseConfig) -> np.ndarray:
    """简化最小值统计：时间平滑后在滑窗内取最小值并补偿偏置。power: (freqs, frames)。"""
    smooth = uniform_filter1d(power, size=5, axis=1)
    win = max(3, int(dcfg.min_window_s * cfg.sample_rate / cfg.hop))
    return dcfg.noise_bias * minimum_filter1d(smooth, size=win, axis=1, mode="nearest")


def wiener_gain(y: np.ndarray, noise: np.ndarray, dcfg: DenoiseConfig) -> np.ndarray:
    """判决引导（decision-directed）先验信噪比 + Wiener 增益。"""
    power = np.abs(y) ** 2
    post = power / (noise + 1e-12)
    gain = np.ones_like(power)
    prev = np.zeros(power.shape[0])
    for t in range(power.shape[1]):
        prio = dcfg.dd_alpha * prev + (1 - dcfg.dd_alpha) * np.maximum(post[:, t] - 1, 0)
        g = prio / (1 + prio)
        gain[:, t] = g
        prev = (g**2) * post[:, t]
    return np.maximum(gain, dcfg.gain_floor)


def spatial_mask(spec: np.ndarray, theta_deg: float, cfg: ArrayConfig, dcfg: DenoiseConfig) -> np.ndarray:
    d = steering(theta_deg, cfg)[1][:, None]
    observed = spec[1] * np.conj(spec[0])
    consistency = np.real(observed * np.conj(d)) / (np.abs(observed) + 1e-12)  # cos(相位误差)
    consistency = uniform_filter(consistency, size=(3, 3))
    mask = ((1 + consistency) / 2) ** dcfg.spatial_power
    return np.maximum(mask, dcfg.spatial_floor)


def target_direction(spec: np.ndarray, cfg: ArrayConfig, grid: np.ndarray | None = None, fmax: float = 4000.0) -> float:
    """噪声协方差相减的 SRP-PHAT：响帧互谱减去静帧互谱，再做相位变换求方位。

    持续存在的风扇等噪声在响帧和静帧里都有，相减后被抵消，剩下的主要是说话人。
    """
    grid = np.arange(-90, 91, 1.0) if grid is None else grid
    e = frame_energy_db(spec)
    loud, quiet = e > np.percentile(e, 75), e < np.percentile(e, 25)
    cross = spec[1] * np.conj(spec[0])
    diff = cross[:, loud].mean(axis=1) - cross[:, quiet].mean(axis=1)
    f = cfg.freqs
    band = (f > 100) & (f < fmax)
    diff = diff[band] / (np.abs(diff[band]) + 1e-12)
    expected = np.exp(-1j * np.outer(tdoa(grid, cfg), 2 * np.pi * f[band]))
    return float(grid[np.argmax(np.real(expected.conj() @ diff))])


def single_channel_wiener(x: np.ndarray, cfg: ArrayConfig, dcfg: DenoiseConfig | None = None) -> np.ndarray:
    """基线：只用 mic0 的经典 Wiener 去噪。"""
    dcfg = dcfg or DenoiseConfig()
    spec = to_stft(x[:1], cfg)[0]
    noise = noise_psd_min_stats(np.abs(spec) ** 2, cfg, dcfg)
    return from_stft(spec * wiener_gain(spec, noise, dcfg), cfg, x.shape[-1])  # (samples,)


def beamform_only(x: np.ndarray, cfg: ArrayConfig, theta_deg: float | None = None) -> np.ndarray:
    """基线：只做延迟求和波束。"""
    spec = to_stft(x, cfg)
    theta = target_direction(spec, cfg) if theta_deg is None else theta_deg
    return from_stft(delay_and_sum(spec, theta, cfg), cfg, x.shape[-1])


def dual_gate_denoise(
    x: np.ndarray,
    cfg: ArrayConfig,
    dcfg: DenoiseConfig | None = None,
    theta_deg: float | None = None,
    adaptive: bool = True,
) -> tuple[np.ndarray, dict]:
    """团队方案：频谱门 × 信噪比自适应空间门。返回 (单声道输出, 诊断信息)。"""
    dcfg = dcfg or DenoiseConfig()
    spec = to_stft(x, cfg)
    theta = target_direction(spec, cfg) if theta_deg is None else theta_deg
    ref = spec[0]
    noise = noise_psd_min_stats(np.abs(ref) ** 2, cfg, dcfg)
    g_spec = wiener_gain(ref, noise, dcfg)
    m_sp = spatial_mask(spec, theta, cfg, dcfg)
    exponent = (1 - g_spec) if adaptive else 1.0  # adaptive=False 为“简单相乘”消融对照
    gain = np.maximum(g_spec * m_sp**exponent, dcfg.gain_floor)
    y = from_stft(ref * gain, cfg, x.shape[-1])
    return y, {"target_azimuth_deg": theta, "mean_gain": float(gain.mean())}
