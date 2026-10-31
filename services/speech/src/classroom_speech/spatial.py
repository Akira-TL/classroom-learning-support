"""双通道空间处理：STFT、方位估计（SRP-PHAT）、导向矢量与波束形成。

坐标约定：两支麦克风位于一条直线上，mic0 为参考。方位角 θ 以阵列中垂线
（正前方）为 0°，朝 mic0 一侧为正，范围 −90°～+90°。θ 为正时声音先到
mic0、后到 mic1。现场安装时记录 mic0 朝向教室哪一侧，写进配置说明。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import istft, stft

SPEED_OF_SOUND = 343.0


@dataclass(frozen=True)
class ArrayConfig:
    mic_distance_m: float = 0.08
    sample_rate: int = 16000
    n_fft: int = 512
    hop: int = 128

    @property
    def freqs(self) -> np.ndarray:
        return np.fft.rfftfreq(self.n_fft, 1.0 / self.sample_rate)


def to_stft(x: np.ndarray, cfg: ArrayConfig) -> np.ndarray:
    """x: (channels, samples) → (channels, freqs, frames)。"""
    _, _, spec = stft(x, fs=cfg.sample_rate, nperseg=cfg.n_fft, noverlap=cfg.n_fft - cfg.hop)
    return spec


def from_stft(spec: np.ndarray, cfg: ArrayConfig, length: int) -> np.ndarray:
    _, y = istft(spec, fs=cfg.sample_rate, nperseg=cfg.n_fft, noverlap=cfg.n_fft - cfg.hop)
    y = y[..., :length]
    if y.shape[-1] < length:
        y = np.pad(y, [(0, 0)] * (y.ndim - 1) + [(0, length - y.shape[-1])])
    return y


def tdoa(theta_deg: float | np.ndarray, cfg: ArrayConfig) -> np.ndarray:
    """mic1 相对 mic0 的到达时延（秒）。"""
    return cfg.mic_distance_m * np.sin(np.deg2rad(theta_deg)) / SPEED_OF_SOUND


def steering(theta_deg: float, cfg: ArrayConfig) -> np.ndarray:
    """导向矢量 (2, freqs)：X1 ≈ X0 · e^{−jωτ}。"""
    w = 2 * np.pi * cfg.freqs
    return np.stack([np.ones_like(w, dtype=complex), np.exp(-1j * w * tdoa(theta_deg, cfg))])


def srp_phat(
    spec: np.ndarray,
    cfg: ArrayConfig,
    grid: np.ndarray,
    fmax: float = 4000.0,
    weights: np.ndarray | None = None,
    noise_cross: np.ndarray | None = None,
) -> np.ndarray:
    """逐帧 SRP-PHAT 空间谱，返回 (frames, len(grid))。

    weights (freqs, frames) 可传入语音存在概率（如 Wiener 增益），让噪声主导的
    时频点少投票。noise_cross (freqs,) 为静帧平均互谱，先从每帧互谱中减去，
    抵消风扇等持续噪声的方向。两者都不传则为经典 SRP-PHAT。
    """
    f = cfg.freqs
    band = (f > 100) & (f < fmax)
    cross = spec[1, band] * np.conj(spec[0, band])
    if noise_cross is not None:
        # 单帧互谱噪声太大，先做约 64 ms 的时间平均，再减去噪声互谱的期望
        cross = uniform_filter1d(cross.real, 8, axis=1) + 1j * uniform_filter1d(cross.imag, 8, axis=1)
        cross = cross - noise_cross[band, None]
    cross /= np.abs(cross) + 1e-12
    if weights is not None:
        cross *= weights[band]
    w = 2 * np.pi * f[band]
    expected = np.exp(-1j * np.outer(tdoa(grid, cfg), w))  # (grid, band)
    return np.real(expected.conj() @ cross).T / band.sum()


def find_peaks_1d(power: np.ndarray, grid: np.ndarray, max_peaks: int, min_sep_deg: float, rel: float) -> list[float]:
    """在角度谱上找局部峰：互相间隔至少 min_sep_deg，强度不低于最高峰的 rel 倍。"""
    order = np.argsort(power)[::-1]
    peaks: list[int] = []
    for idx in order:
        if len(peaks) >= max_peaks or power[idx] < rel * power[order[0]]:
            break
        left, right = power[max(idx - 1, 0)], power[min(idx + 1, len(power) - 1)]
        if power[idx] < left or power[idx] < right:
            continue
        if all(abs(grid[idx] - grid[p]) >= min_sep_deg for p in peaks):
            peaks.append(int(idx))
    return [float(grid[p]) for p in peaks]


def frame_energy_db(spec: np.ndarray) -> np.ndarray:
    return 10 * np.log10(np.mean(np.abs(spec[0]) ** 2, axis=0) + 1e-12)


def quiet_cross_spectrum(spec: np.ndarray, quantile: float = 25) -> np.ndarray:
    """最安静的一部分帧的平均互谱，用作持续噪声的空间特征。quantile=100 即全部帧。"""
    e = frame_energy_db(spec)
    quiet = e <= np.percentile(e, quantile)
    return (spec[1][:, quiet] * np.conj(spec[0][:, quiet])).mean(axis=1)


def estimate_sources(
    spec: np.ndarray,
    cfg: ArrayConfig,
    max_sources: int = 3,
    grid: np.ndarray | None = None,
    min_sep_deg: float = 20.0,
    rel: float = 0.35,
    noise_cross: np.ndarray | None = None,
) -> list[float]:
    """估计一段音频中的主要声源方位：响帧逐帧取 SRP-PHAT 峰值投票，平滑后取峰。

    noise_cross：持续噪声的平均互谱。会话里应传入语音开始前静音段的互谱；不传时
    用本段最安静的帧近似。先从短时互谱中扣除，风扇、投影仪的方向就不会被当成说话人。
    """
    grid = np.arange(-90, 91, 1.0) if grid is None else grid
    noise_cross = quiet_cross_spectrum(spec) if noise_cross is None else noise_cross
    p = srp_phat(spec, cfg, grid, noise_cross=noise_cross)
    energy = frame_energy_db(spec)
    active = energy > np.percentile(energy, 50)
    votes = np.bincount(np.argmax(p[active], axis=1), minlength=len(grid)).astype(float)
    votes = np.convolve(votes, np.ones(5) / 5, mode="same")
    return find_peaks_1d(votes, grid, max_sources, min_sep_deg, rel)


def delay_and_sum(spec: np.ndarray, theta_deg: float, cfg: ArrayConfig) -> np.ndarray:
    """经典延迟求和波束（基线）。输出以 mic0 为相位参考。"""
    d = steering(theta_deg, cfg)
    return 0.5 * (spec[0] + spec[1] * np.conj(d[1])[:, None])
