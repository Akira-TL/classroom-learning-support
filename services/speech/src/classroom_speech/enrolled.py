"""创新点 4：声纹注册的选择性多人分离（Enrolled Selective Separation, ESS）。

两支麦克风的空间信息最多干净地分开两个方向，三人以上同时说话时“看方向”
不够用。课堂有一个独特条件：学生是固定的一群人，可以提前注册。

- 注册：每人在座位上读 2 句，学一本“声音字典”（KL-NMF 基向量），同时用注册
  录音估计座位方位。全班注册，字典叠在一起就是“班级声音库”。
- 认人：用整个班级声音库解释混合音频（字典固定，只解激活，带稀疏惩罚），
  每人的激活能量即“此刻谁在说话”；再只保留活跃的人重新求解。
- 选择性：逐帧判定活跃人数。只有一人说话的帧整帧交给此人（只去噪，不做
  分离）；两人以上的帧才做时频掩码分离，单人语音不受分离损伤。
- 空间—音色融合：重叠帧的掩码 = 音色掩码 × 方位似然^γ(f)。γ(f) 由物理可
  分辨度决定：两人方位在频率 f 上的相位差越接近 0 或 2π（低频、空间混叠频点），
  空间线索越不可信，越依赖音色。
- 噪声字典：从语音开始前的静音段现学，让风扇、嘈杂声有自己的去处，不被硬塞
  给某个学生。

全部为 DSP，可在 CPU 实时运行；神经目标说话人提取模型（如 WeSep、SpEx+）可通过
`EnrolledExtractor` 协议接入，输入同样是注册音频 + 混合音频。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from scipy.ndimage import uniform_filter, uniform_filter1d

from .spatial import ArrayConfig, estimate_sources, frame_energy_db, from_stft, steering, to_stft, tdoa

EPS = 1e-10


@dataclass(frozen=True)
class EnrollConfig:
    rank: int = 24
    id_rank: int = 8
    noise_rank: int = 8
    max_speakers: int = 8
    learn_iters: int = 120
    solve_iters: int = 60
    sparsity: float = 0.0
    # 逐个加入说话人时，第 n 个人至少要多解释 gain_base·(2/n)^gain_decay 的 KL 散度
    first_gain: float = 0.08
    gain_base: float = 0.058
    gain_decay: float = 1.4
    gain_min: float = 0.015
    frame_active: float = 0.25
    solo_share: float = 0.8
    mask_power: float = 1.5
    spatial_kappa: float = 4.0
    spatial_weight: float = 1.0
    mask_floor: float = 0.03
    fmin: float = 80.0


@dataclass
class SpeakerProfile:
    speaker_id: str
    basis: np.ndarray  # (freqs, rank)，列归一化，用于分离
    id_basis: np.ndarray  # (freqs, id_rank)，低秩字典，用于认人（秩低更“专属”，不易替别人解释）
    azimuth_deg: float | None = None


@dataclass
class SeparationReport:
    pool_size: int
    detected: list[str]
    gains: list[float]
    frame_counts: np.ndarray  # 每帧活跃人数
    overlap_ratio: float
    separated_ratio: float
    activity: np.ndarray = field(repr=False)  # (K, frames) 活跃说话人逐帧活跃度


class EnrolledExtractor(Protocol):
    """神经目标说话人提取接口：给注册音频和混合音频，返回该人的语音。"""

    name: str

    def extract(self, mixture: np.ndarray, enrollment: np.ndarray, sample_rate: int = 16000) -> np.ndarray: ...


def _norm_cols(w: np.ndarray) -> np.ndarray:
    return w / (w.sum(axis=0, keepdims=True) + EPS)


def nmf_kl(v: np.ndarray, rank: int, iters: int, rng: np.random.Generator, w: np.ndarray | None = None,
           fixed_w: int = 0, sparsity: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """KL 散度 NMF（乘性更新）。w 的前 fixed_w 列固定不学；sparsity 为激活的 L1 惩罚。"""
    f, t = v.shape
    if w is None:
        w = rng.uniform(0.1, 1.0, (f, rank))
    elif w.shape[1] < rank:
        w = np.hstack([w, rng.uniform(0.1, 1.0, (f, rank - w.shape[1]))])
    w = _norm_cols(w)
    h = np.full((w.shape[1], t), v.mean() + EPS)
    for _ in range(iters):
        wh = w @ h + EPS
        h *= (w.T @ (v / wh)) / (w.sum(axis=0)[:, None] + sparsity + EPS)
        if fixed_w < w.shape[1]:
            wh = w @ h + EPS
            free = slice(fixed_w, None)
            w[:, free] *= ((v / wh) @ h[free].T) / (h[free].sum(axis=1)[None, :] + EPS)
            w[:, free] = _norm_cols(w[:, free])
    return w, h


def _speech_frames(spec: np.ndarray, margin_db: float = 10.0) -> np.ndarray:
    e = frame_energy_db(spec)
    return e > np.percentile(e, 10) + margin_db


def enroll(speaker_id: str, x: np.ndarray, cfg: ArrayConfig, ecfg: EnrollConfig | None = None, seed: int = 0) -> SpeakerProfile:
    """x：(2, samples) 双通道注册录音，或 (samples,) 单通道（此时不记录方位）。"""
    ecfg = ecfg or EnrollConfig()
    x2 = x if x.ndim == 2 else np.stack([x, x])
    spec = to_stft(x2, cfg)
    v = np.abs(spec[0][:, _speech_frames(spec)])
    rng = np.random.default_rng(seed)
    w, _ = nmf_kl(v, ecfg.rank, ecfg.learn_iters, rng)
    wid, _ = nmf_kl(v, ecfg.id_rank, ecfg.learn_iters, rng)
    az = None
    if x.ndim == 2:
        est = estimate_sources(spec, cfg, max_sources=1)
        az = est[0] if est else None
    return SpeakerProfile(speaker_id, w.astype(np.float32), wid.astype(np.float32), az)


def _kl(v: np.ndarray, wh: np.ndarray) -> float:
    return float((v * np.log((v + EPS) / (wh + EPS)) - v + wh).sum())


def identify_speakers(v: np.ndarray, speech: np.ndarray, profiles: list[SpeakerProfile], wn: np.ndarray,
                      ecfg: EnrollConfig, rng: np.random.Generator) -> tuple[list[int], list[float]]:
    """“剥洋葱”式认人：先排序，再逐个加入，直到新加的人解释不了多少新东西。

    1. 用全班低秩字典一次性解释混合音频，逐帧算每人的能量占比；
    2. 依次挑“在剩余人里占主导最多”的人（已入选者不再参与比较，近处大声的人
       不会一直盖住远处小声的人），得到候选顺序；
    3. 按顺序逐个加入重新拟合，记录 KL 散度的相对下降；下降低于随人数递减的
       门限即停止。返回 (活跃下标, 每一步的相对增益)。
    """
    r = ecfg.id_rank
    vs = v[:, speech]
    if vs.shape[1] < 5:
        return [], []
    w = np.hstack([p.id_basis for p in profiles] + [wn]).astype(np.float32)
    _, h = nmf_kl(vs, w.shape[1], 40, rng, w=w.copy(), fixed_w=w.shape[1])
    e = np.stack([(w[:, i * r:(i + 1) * r] @ h[i * r:(i + 1) * r]).sum(axis=0) for i in range(len(profiles))])
    share = uniform_filter1d(e, 7, axis=1)
    share = share / (share.sum(axis=0, keepdims=True) + EPS)
    order, rem = [], list(range(len(profiles)))
    for _ in range(min(ecfg.max_speakers + 1, len(profiles))):
        sub = share[rem]
        top = sub.argmax(axis=0)
        dominance = [(sub[j] * (top == j)).mean() for j in range(len(rem))]
        order.append(rem.pop(int(np.argmax(dominance))))
    prev = None
    gains: list[float] = []
    active: list[int] = []
    for n in range(len(order) + 1):
        wn_ = np.hstack([profiles[i].id_basis for i in order[:n]] + [wn]).astype(np.float32)
        _, hh = nmf_kl(vs, wn_.shape[1], 40, rng, w=wn_.copy(), fixed_w=wn_.shape[1])
        cur = _kl(vs, wn_ @ hh)
        if prev is not None:
            g = (prev - cur) / (prev + EPS)
            gains.append(round(float(g), 4))
            k = n - 1  # 正在考虑第 n 个人（已有 k 人）
            need = ecfg.first_gain if k == 1 else max(ecfg.gain_min, ecfg.gain_base * (2 / k) ** ecfg.gain_decay) if k else 0.0
            if g < need or len(active) >= ecfg.max_speakers:
                break
            active.append(order[n - 1])
        prev = cur
    return active, gains


def spatial_resolvability(azimuths: list[float], cfg: ArrayConfig) -> np.ndarray:
    """(freqs,) 每个频点上最难区分的一对说话人的相位可分辨度 |sin(Δφ/2)| ∈ [0, 1]。"""
    if len(azimuths) < 2:
        return np.zeros_like(cfg.freqs)
    w = 2 * np.pi * cfg.freqs
    taus = np.array([tdoa(a, cfg) for a in azimuths])
    res = np.ones_like(w)
    for i in range(len(taus)):
        for j in range(i + 1, len(taus)):
            res = np.minimum(res, np.abs(np.sin(w * (taus[i] - taus[j]) / 2)))
    return res


def _spatial_likelihood(spec: np.ndarray, azimuths: list[float], cfg: ArrayConfig, kappa: float) -> np.ndarray:
    obs = spec[1] * np.conj(spec[0])
    obs = obs / (np.abs(obs) + EPS)
    out = []
    for az in azimuths:
        d = steering(az, cfg)[1][:, None]
        out.append(np.exp(kappa * (uniform_filter(np.real(obs * np.conj(d)), size=(3, 3)) - 1)))
    return np.stack(out)


def enrolled_separate(
    x: np.ndarray,
    profiles: list[SpeakerProfile],
    cfg: ArrayConfig,
    ecfg: EnrollConfig | None = None,
    noise_ref: np.ndarray | None = None,
    use_spatial: bool = True,
    selective: bool = True,
    known_active: list[int] | None = None,
    seed: int = 0,
) -> tuple[np.ndarray, list[int], SeparationReport]:
    """返回 (streams (K, samples), 活跃说话人在 profiles 中的下标, 报告)。

    noise_ref：语音开始前的一段双通道静音（会话里由前端 VAD 提供），用来学噪声字典；
    不传时取能量最低的 15% 帧。known_active：已知谁在说话时跳过认人（消融用）。
    """
    ecfg = ecfg or EnrollConfig()
    rng = np.random.default_rng(seed)
    spec = to_stft(x, cfg)
    v = np.abs(spec[0]).astype(np.float32)
    band = cfg.freqs >= ecfg.fmin
    if noise_ref is not None and noise_ref.shape[-1] >= cfg.n_fft:
        vn = np.abs(to_stft(noise_ref, cfg)[0])
    else:
        e = frame_energy_db(spec)
        vn = v[:, e <= np.percentile(e, 15)]
    wn, _ = nmf_kl(vn, ecfg.noise_rank, 60, rng)
    r = ecfg.rank

    def solve(idx: list[int]) -> tuple[np.ndarray, np.ndarray]:
        w = np.hstack([profiles[i].basis for i in idx] + [wn])
        w[~band] *= 0.0
        w = _norm_cols(w + EPS)
        _, h = nmf_kl(v, w.shape[1], ecfg.solve_iters, rng, w=w.copy(), fixed_w=w.shape[1], sparsity=ecfg.sparsity * v.mean())
        return w, h

    def energies(w: np.ndarray, h: np.ndarray, k: int) -> np.ndarray:
        return np.stack([(w[:, i * r:(i + 1) * r] @ h[i * r:(i + 1) * r]).sum(axis=0) for i in range(k)])

    gains: list[float] = []
    if known_active is None:
        active, gains = identify_speakers(v, _speech_frames(spec), profiles, wn, ecfg, rng)
        if not active:
            active = [0] if profiles else []
    else:
        active = list(known_active)

    w, h = solve(active)
    k = len(active)
    parts = np.stack([w[:, i * r:(i + 1) * r] @ h[i * r:(i + 1) * r] for i in range(k)])  # (K, F, T)
    noise_part = w[:, k * r:] @ h[k * r:]
    p = ecfg.mask_power
    num = parts**p
    spec_mask = num / (num.sum(axis=0) + noise_part**p + EPS)

    masks = spec_mask
    azs = [profiles[i].azimuth_deg for i in active]
    if use_spatial and k >= 2 and all(a is not None for a in azs):
        gamma = ecfg.spatial_weight * spatial_resolvability(azs, cfg)[None, :, None]
        lik = _spatial_likelihood(spec, azs, cfg, ecfg.spatial_kappa)
        fused = spec_mask * lik**gamma
        speech_total = spec_mask.sum(axis=0, keepdims=True)
        masks = fused / (fused.sum(axis=0, keepdims=True) + EPS) * speech_total

    # 逐帧活跃度：此人在语音能量里的占比
    e = parts.sum(axis=1)
    share = uniform_filter1d(e / (e.sum(axis=0, keepdims=True) + EPS), size=7, axis=1)
    speech = _speech_frames(spec, 6.0)
    act = (share > ecfg.frame_active) & speech[None, :]
    counts = act.sum(axis=0)
    # 有把握的单人帧：主讲者占比 ≥ solo_share。只有这些帧整帧路由、不做分离
    solo_frames = speech & (share.max(axis=0) >= ecfg.solo_share)
    counts = np.where(solo_frames, 1, np.maximum(counts, 2 * (speech & ~solo_frames)))
    if selective and k >= 2:
        speech_mask = masks.sum(axis=0, keepdims=True)
        owner = (np.arange(k)[:, None] == share.argmax(axis=0)[None, :]).astype(float)[:, None, :]
        s_w = uniform_filter1d(solo_frames.astype(float), size=5)[None, None, :]
        masks = s_w * owner * speech_mask + (1 - s_w) * masks
    masks = np.maximum(masks, ecfg.mask_floor)
    streams = np.stack([from_stft(spec[0] * m, cfg, x.shape[-1]) for m in masks])
    n_speech = max(int(speech.sum()), 1)
    report = SeparationReport(
        pool_size=len(profiles), detected=[profiles[i].speaker_id for i in active], gains=gains, frame_counts=counts,
        overlap_ratio=float(((counts >= 2) & speech).sum() / n_speech),
        separated_ratio=float(((counts >= 2) & speech).sum() / max(len(counts), 1)) if selective else 1.0, activity=share,
    )
    return streams, active, report
