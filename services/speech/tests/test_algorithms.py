import numpy as np
import pytest

from classroom_speech.denoise import dual_gate_denoise, single_channel_wiener, target_direction
from classroom_speech.events import EventType, Reliability
from classroom_speech.pipeline import Session
from classroom_speech.separation import align_to_azimuth
from classroom_speech.spatial import ArrayConfig, estimate_sources, to_stft, tdoa

CFG = ArrayConfig()


def fractional_delay(x: np.ndarray, delay_s: float, sr: int) -> np.ndarray:
    n = len(x)
    freqs = np.fft.rfftfreq(n, 1 / sr)
    return np.fft.irfft(np.fft.rfft(x) * np.exp(-2j * np.pi * freqs * delay_s), n)


def two_mic(source: np.ndarray, azimuth: float) -> np.ndarray:
    return np.stack([source, fractional_delay(source, float(tdoa(azimuth, CFG)), CFG.sample_rate)])


def burst_noise(rng, seconds=2.0):
    x = rng.standard_normal(int(seconds * CFG.sample_rate))
    env = (np.sin(np.linspace(0, 12 * np.pi, len(x))) > 0).astype(float)
    return x * env


@pytest.mark.parametrize("azimuth", [-50.0, -20.0, 0.0, 30.0, 60.0])
def test_estimate_sources_free_field(azimuth):
    rng = np.random.default_rng(0)
    x = two_mic(burst_noise(rng), azimuth)
    est = estimate_sources(to_stft(x, CFG), CFG, max_sources=1)
    assert abs(est[0] - azimuth) <= 6


def test_target_direction_ignores_steady_noise():
    rng = np.random.default_rng(1)
    speech = two_mic(burst_noise(rng), -30.0)
    fan = two_mic(rng.standard_normal(speech.shape[1]) * 0.5, 60.0)
    assert abs(target_direction(to_stft(speech + fan, CFG), CFG) + 30) <= 8


def test_dual_gate_preserves_length_and_beats_raw():
    rng = np.random.default_rng(2)
    speech = two_mic(burst_noise(rng), -30.0)
    fan = two_mic(rng.standard_normal(speech.shape[1]), 60.0)
    x = speech + fan
    y, diag = dual_gate_denoise(x, CFG)
    assert y.shape == (x.shape[1],)
    err_raw = np.mean((x[0] - speech[0]) ** 2)
    assert np.mean((y - speech[0]) ** 2) < err_raw
    assert single_channel_wiener(x, CFG).shape == (x.shape[1],)


def test_align_to_azimuth_recovers_order():
    rng = np.random.default_rng(3)
    a, b = burst_noise(rng), rng.standard_normal(2 * CFG.sample_rate)
    x = two_mic(a, -40.0) + two_mic(b, 35.0)
    shuffled = np.stack([b, a])
    assert align_to_azimuth(shuffled, x, [-40.0, 35.0], CFG) == [1, 0]


def test_session_emits_contract_events_without_asr(tmp_path):
    rng = np.random.default_rng(4)
    quiet = np.zeros((2, CFG.sample_rate)) + 1e-4 * rng.standard_normal((2, CFG.sample_rate))
    x = np.concatenate([quiet, two_mic(burst_noise(rng, 1.5) * 0.3, 20.0), quiet], axis=1).astype(np.float32)
    s = Session("ses_test", tmp_path, asr=None, data_origin="simulated")
    pcm = (np.clip(x.T, -1, 1) * 32767).astype("<i2").tobytes()
    s.push_pcm(pcm)
    s.end()
    types = [e.event_type for e in s.events]
    assert types[-1] == EventType.SESSION_ENDED
    finals = [e for e in s.events if e.event_type == EventType.TRANSCRIPT_FINAL]
    assert finals and all(e.text is None and e.reliability_state == Reliability.FAILED for e in finals)
    assert [e.sequence for e in s.events] == list(range(1, len(s.events) + 1))
