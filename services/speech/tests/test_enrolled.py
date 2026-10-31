import numpy as np

from classroom_speech.enrolled import enroll, enrolled_separate, spatial_resolvability
from classroom_speech.separation_v2 import separate
from classroom_speech.spatial import ArrayConfig, tdoa

CFG = ArrayConfig()


def voice(f0: float, seconds: float, rng, vibrato: float = 3.0) -> np.ndarray:
    t = np.arange(int(seconds * CFG.sample_rate)) / CFG.sample_rate
    f = f0 * (1 + 0.03 * np.sin(2 * np.pi * vibrato * t))
    phase = 2 * np.pi * np.cumsum(f) / CFG.sample_rate
    x = sum(np.sin(k * phase) / k for k in range(1, 12))
    env = (np.sin(2 * np.pi * 1.5 * t + rng.uniform(0, 6)) > -0.3).astype(float)
    return (x * env * 0.1).astype(np.float32)


def two_mic(s: np.ndarray, az: float) -> np.ndarray:
    n = len(s)
    freqs = np.fft.rfftfreq(n, 1 / CFG.sample_rate)
    return np.stack([s, np.fft.irfft(np.fft.rfft(s) * np.exp(-2j * np.pi * freqs * float(tdoa(az, CFG))), n)]).astype(np.float32)


def si_sdr(ref, est):
    ref, est = ref - ref.mean(), est - est.mean()
    s = (est @ ref) / (ref @ ref) * ref
    return 10 * np.log10(np.sum(s**2) / np.sum((est - s) ** 2))


def test_enrolled_separation_identifies_and_improves():
    rng = np.random.default_rng(0)
    f0s, azs = [110.0, 190.0, 300.0], [-40.0, 10.0, 50.0]
    profiles = [enroll(f"S{i}", two_mic(voice(f, 3.0, rng), a), CFG, seed=i) for i, (f, a) in enumerate(zip(f0s, azs))]
    a, b = voice(f0s[0], 3.0, rng), voice(f0s[2], 3.0, rng)
    noise = 0.003 * rng.standard_normal((2, len(a)))
    x = two_mic(a, azs[0]) + two_mic(b, azs[2]) + noise
    streams, active, report = enrolled_separate(x, profiles, CFG)
    assert sorted(active) == [0, 2]
    for ref, idx in [(a, 0), (b, 2)]:
        out = streams[active.index(idx)]
        assert si_sdr(ref, out) > si_sdr(ref, x[0]) + 3
    assert report.frame_counts.shape[0] > 0


def test_spatial_resolvability_low_frequency_is_ambiguous():
    r = spatial_resolvability([-30.0, 30.0], CFG)
    assert r[2] < 0.1 and r.max() > 0.9


def test_separate_v2_falls_back_without_enrollment():
    rng = np.random.default_rng(1)
    x = two_mic(voice(120.0, 2.0, rng), -40.0) + two_mic(voice(260.0, 2.0, rng), 35.0)
    streams, report = separate(x, [35.0, -40.0], CFG)
    assert streams.shape == (2, x.shape[1])
    assert hasattr(report, "frame_overlap") and report.overlap_ratio() >= 0
