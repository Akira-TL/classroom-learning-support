"""创新点 2、3：重叠感知的选择性分离 + 方位锚定的输出对齐。

- detect_overlap：按 0.5 s 窗统计逐帧主方位；同一窗内出现两个间隔足够、
  票数都不低的方位峰，判定为多人同时说话。
- anchored_masks：以每位说话人的方位为锚，计算每个时频点相位差与各方位的
  一致度，归一化成软掩码（另设一个“散射/噪声”类，防止把混响硬塞给某人）。
- selective_separate：只在重叠窗内做时频掩码分离；单人窗整帧交给该方位的
  说话人，不做时频掩码，避免对干净语音的无谓损伤。
- align_to_azimuth：神经分离模型（如 MossFormer2）的输出顺序是任意的。用
  指向各方位的锚定流作参考，按相关度做最优匹配，把“第几路”固定成“哪个
  方位”，跨片段保持一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations

import numpy as np
from scipy.ndimage import uniform_filter, uniform_filter1d

from .spatial import (
    ArrayConfig,
    find_peaks_1d,
    frame_energy_db,
    from_stft,
    quiet_cross_spectrum,
    srp_phat,
    steering,
    to_stft,
)


@dataclass(frozen=True)
class SeparationConfig:
    window_s: float = 0.5
    hop_s: float = 0.25
    min_sep_deg: float = 20.0
    second_peak_ratio: float = 0.3
    concentration: float = 8.0
    diffuse_weight: float = 0.15
    mask_floor: float = 0.05


@dataclass
class OverlapReport:
    windows: list[dict] = field(default_factory=list)

    def overlap_ratio(self) -> float:
        speech = [w for w in self.windows if w["speech"]]
        return sum(w["overlap"] for w in speech) / max(len(speech), 1)


def detect_overlap(
    spec: np.ndarray, cfg: ArrayConfig, scfg: SeparationConfig | None = None, noise_cross: np.ndarray | None = None
) -> OverlapReport:
    scfg = scfg or SeparationConfig()
    grid = np.arange(-90, 91, 1.0)
    noise_cross = quiet_cross_spectrum(spec) if noise_cross is None else noise_cross
    p = srp_phat(spec, cfg, grid, noise_cross=noise_cross)
    e = frame_energy_db(spec)
    speech_frames = e > np.percentile(e, 20) + 6
    fps = cfg.sample_rate / cfg.hop
    win, hop = int(scfg.window_s * fps), int(scfg.hop_s * fps)
    report = OverlapReport()
    for start in range(0, max(p.shape[0] - win, 1), hop):
        sel = np.zeros(p.shape[0], bool)
        sel[start : start + win] = True
        sel &= speech_frames
        entry = {"start_ms": int(start / fps * 1000), "end_ms": int((start + win) / fps * 1000), "speech": bool(sel.sum() > win * 0.3)}
        if not entry["speech"]:
            entry.update(overlap=False, azimuths=[])
            report.windows.append(entry)
            continue
        votes = np.bincount(np.argmax(p[sel], axis=1), minlength=len(grid)).astype(float)
        votes = np.convolve(votes, np.ones(5), mode="same")
        peaks = find_peaks_1d(votes, grid, 2, scfg.min_sep_deg, scfg.second_peak_ratio)
        entry.update(overlap=len(peaks) >= 2, azimuths=peaks)
        report.windows.append(entry)
    return report


def anchored_masks(spec: np.ndarray, azimuths: list[float], cfg: ArrayConfig, scfg: SeparationConfig) -> np.ndarray:
    """(K, freqs, frames) 软掩码，每个说话人一个。"""
    observed = spec[1] * np.conj(spec[0])
    observed = observed / (np.abs(observed) + 1e-12)
    scores = []
    for az in azimuths:
        d = steering(az, cfg)[1][:, None]
        cos_err = uniform_filter(np.real(observed * np.conj(d)), size=(3, 3))
        scores.append(np.exp(scfg.concentration * cos_err))
    scores = np.stack(scores)
    diffuse = scfg.diffuse_weight * np.exp(scfg.concentration * 0.0) * np.ones_like(scores[0])
    return scores / (scores.sum(axis=0) + diffuse)


def mask_separate(x: np.ndarray, azimuths: list[float], cfg: ArrayConfig, scfg: SeparationConfig | None = None) -> np.ndarray:
    """全程时频掩码分离（消融对照：不做重叠检测，处处分离）。返回 (K, samples)。"""
    scfg = scfg or SeparationConfig()
    spec = to_stft(x, cfg)
    masks = np.maximum(anchored_masks(spec, azimuths, cfg, scfg), scfg.mask_floor)
    return np.stack([from_stft(spec[0] * m, cfg, x.shape[-1]) for m in masks])


def selective_separate(
    x: np.ndarray,
    azimuths: list[float],
    cfg: ArrayConfig,
    scfg: SeparationConfig | None = None,
    noise_cross: np.ndarray | None = None,
) -> tuple[np.ndarray, OverlapReport]:
    """团队方案：重叠窗做掩码分离，单人窗整帧路由给对应方位。返回 ((K, samples), 报告)。"""
    scfg = scfg or SeparationConfig()
    spec = to_stft(x, cfg)
    noise_cross = quiet_cross_spectrum(spec) if noise_cross is None else noise_cross
    report = detect_overlap(spec, cfg, scfg, noise_cross)
    masks = np.maximum(anchored_masks(spec, azimuths, cfg, scfg), scfg.mask_floor)
    n_frames = spec.shape[-1]
    fps = cfg.sample_rate / cfg.hop
    overlap_w = np.zeros(n_frames)
    counts = np.zeros(n_frames)
    win_route = np.zeros((len(azimuths), n_frames))
    win_counts = np.zeros(n_frames)
    anchors = np.array(azimuths)
    for w in report.windows:
        a, b = int(w["start_ms"] / 1000 * fps), min(int(w["end_ms"] / 1000 * fps), n_frames)
        counts[a:b] += 1
        if w["overlap"]:
            overlap_w[a:b] += 1
        elif w["speech"] and w["azimuths"]:
            # 单人窗：用 0.5 s 窗的主方位（比逐帧方位稳）整窗路由给最近的说话人
            win_route[int(np.argmin(np.abs(anchors - w["azimuths"][0]))), a:b] += 1
            win_counts[a:b] += 1
    overlap_w = overlap_w / np.maximum(counts, 1)
    # 窗口没覆盖到的帧（句首句尾）退回逐帧主方位，平滑后路由
    grid = np.arange(-90, 91, 1.0)
    frame_az = grid[np.argmax(srp_phat(spec, cfg, grid, noise_cross=noise_cross), axis=1)]
    nearest = np.argmin(np.abs(frame_az[None, :] - anchors[:, None]), axis=0)
    frame_route = np.stack([uniform_filter1d((nearest == k).astype(float), size=int(0.4 * fps)) for k in range(len(azimuths))])
    route = np.where(win_counts > 0, win_route / np.maximum(win_counts, 1), frame_route)
    route = np.maximum(route, scfg.mask_floor)
    o = uniform_filter1d(overlap_w, size=int(0.1 * fps))[None, None, :]
    gains = o * masks + (1 - o) * route[:, None, :]
    out = np.stack([from_stft(spec[0] * g, cfg, x.shape[-1]) for g in gains])
    return out, report


def align_to_azimuth(outputs: np.ndarray, x: np.ndarray, azimuths: list[float], cfg: ArrayConfig) -> list[int]:
    """把任意顺序的分离输出对齐到方位：返回 order，使 outputs[order[k]] 对应 azimuths[k]。"""
    anchors = mask_separate(x, azimuths, cfg)
    n = min(outputs.shape[-1], anchors.shape[-1])

    def corr(a: np.ndarray, b: np.ndarray) -> float:
        a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
        return float(abs(a @ b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))

    k = len(azimuths)
    sim = np.array([[corr(outputs[j], anchors[i]) for j in range(outputs.shape[0])] for i in range(k)])
    best = max(permutations(range(outputs.shape[0]), k), key=lambda perm: sum(sim[i, perm[i]] for i in range(k)))
    return list(best)
