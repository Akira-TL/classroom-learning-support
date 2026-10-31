import numpy as np
import pytest

from classroom_speech.math_asr import (
    MathGuardedAsr,
    OracleAsr,
    SimulatedConfusionAsr,
    arbitrate,
    confusion_class,
    counterfactuals,
    extract_claims,
    symmetric_hotwords,
)

SR = 16000


def keys(text):
    return [c.key for c in extract_claims(text)]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("每份是它的四分之一。", ["fraction:1/4"]),
        ("每份是它的十分之一。", ["fraction:1/10"]),
        ("这个图形没有平均分。", ["property:¬平均分"]),
        ("这两块不一样大。", ["property:¬一样大"]),
        ("把圆平均分成4份", ["partition:equalx4"]),
        ("百分之二十", ["fraction:20/100"]),
        ("我觉得是1/4", ["fraction:1/4"]),
    ],
)
def test_extract_claims(text, expected):
    assert keys(text) == expected


def test_counterfactuals_cover_digit_and_negation():
    (frac,) = extract_claims("四分之一")
    assert "十分之一" in counterfactuals(frac)
    (neg,) = extract_claims("没有平均分")
    assert counterfactuals(neg) == ["平均分"]
    (frac20,) = extract_claims("百分之二十")
    assert counterfactuals(frac20) == []  # “二十”里的“十”是位值，不和“四”混


def test_symmetric_hotwords_add_whole_confusion_class():
    hw = symmetric_hotwords("把一张纸平均分成4份，每份是它的几分之几？")
    assert {"四分之一", "十分之一", "平均分", "没有平均分"} <= set(hw)
    assert set(confusion_class("七分之一")) == {"七分之一", "一分之一", "七分之七", "一分之七"}


def test_guard_never_rewrites_text():
    asr = MathGuardedAsr(OracleAsr(["每份是它的十分之一。"]))
    r = asr.transcribe(np.zeros(SR, np.float32), SR, context={"question": "把一张纸平均分成4份，每份是它的几分之几？"})
    assert r.text == "每份是它的十分之一。"
    # 无热词能力、无时间戳 → 无法核实；与题目不符 → 待核验，不改写
    assert r.reliability == "needs_review"
    assert any("context_mismatch" in t["flags"] for t in r.math_terms)


def test_probe_flags_unstable_and_keeps_alternative():
    ref = "每份是它的四分之一。"
    asr = MathGuardedAsr(SimulatedConfusionAsr(ref, {5: 0.5}))  # 裕度小：被“十分之一”热词一拉就变
    r = asr.transcribe(np.zeros(SR, np.float32), SR, context={"question": "平均分成4份"})
    assert r.text == ref and r.reliability == "needs_review"
    assert r.candidates[0]["alternatives"][0]["surface"] == "十分之一"


def test_probe_confirms_robust_student_error():
    ref = "每份是它的十分之一。"
    asr = MathGuardedAsr(SimulatedConfusionAsr(ref, {5: 3.0, 8: 3.0}))  # 声学证据扎实：学生确实说了十分之一
    r = asr.transcribe(np.zeros(SR, np.float32), SR, context={"question": "平均分成4份"})
    assert r.text == ref and r.reliability == "usable"
    assert "verified_as_spoken" in r.math_terms[0]["flags"]


def test_negation_dropped_by_asr_is_caught():
    ref = "这样分没有平均分。"
    asr = MathGuardedAsr(SimulatedConfusionAsr(ref, {3: -0.5}))  # 通用解码把“没有”吞了
    r = asr.transcribe(np.zeros(SR, np.float32), SR, context={"question": "这样分是平均分吗？"})
    assert "没有" not in r.text
    assert r.reliability == "needs_review"


def _tone(f0_start, f0_end, dur=0.3, fric_ms=0, hf=True):
    rng = np.random.default_rng(0)
    t = np.arange(int(dur * SR)) / SR
    f0 = np.linspace(f0_start, f0_end, len(t))
    voiced = sum(np.sin(2 * np.pi * np.cumsum(f0 * k) / SR) / k for k in range(1, 8))
    n = int(fric_ms * SR / 1000)
    noise = rng.standard_normal(n)
    noise = np.diff(noise, prepend=0) if hf else noise  # 一阶差分 → 高频为主
    return np.concatenate([np.zeros(800), 0.3 * noise, voiced * np.hanning(len(t)) ** 0.3, np.zeros(800)]).astype(np.float32)


def test_tone_arbiter_falling_vs_rising():
    assert arbitrate(_tone(260, 170, fric_ms=80), "四", "十").favors == "四"
    assert arbitrate(_tone(200, 260, fric_ms=80), "四", "十").favors == "十"


def test_onset_arbiter_yi_vs_qi():
    assert arbitrate(_tone(240, 240), "一", "七").favors == "一"
    assert arbitrate(_tone(240, 240, fric_ms=120), "一", "七").favors == "七"
