"""转换桥：输出必须能被教学应用当前的 app-draft-1 模型原样接受（仓库里有应用代码时直接用它校验）。"""

import sys
from pathlib import Path

import numpy as np
import pytest

from classroom_speech.app_bridge import APP_EVENT_KEYS, AppEventMapper, SyntheticRefused
from classroom_speech.engines import AsrResult
from classroom_speech.events import EventType
from classroom_speech.pipeline import Session
from classroom_speech.spatial import ArrayConfig

from test_algorithms import burst_noise, two_mic

CFG = ArrayConfig()
APP_DIR = Path(__file__).resolve().parents[2] / "application"


def app_model():
    if not (APP_DIR / "teaching" / "audio" / "models.py").exists():
        pytest.skip("仓库里没有教学应用代码")
    sys.path.insert(0, str(APP_DIR))
    from teaching.audio.models import SpeechEvent as AppSpeechEvent

    return AppSpeechEvent


class FixedAsr:
    name = "fixed-test-engine"

    def transcribe(self, audio, sample_rate):
        return AsrResult(text="有四块就是四分之一。", engine=self.name)


def lesson_events(tmp_path, asr, data_origin="live"):
    rng = np.random.default_rng(4)
    quiet = 1e-4 * rng.standard_normal((2, CFG.sample_rate))
    x = np.concatenate([quiet, two_mic(burst_noise(rng, 1.5) * 0.3, 20.0), quiet], axis=1).astype(np.float32)
    s = Session("ses_bridge", tmp_path, asr=asr, data_origin=data_origin)
    s.push(x)
    s.report_gap(3000, 3400, "stream_dropout")
    s.end()
    return s.events


def test_mapped_events_pass_app_model(tmp_path):
    AppSpeechEvent = app_model()
    mapper = AppEventMapper()
    out = [e for ev in lesson_events(tmp_path, FixedAsr()) for e in mapper.map(ev)]
    for e in out:
        assert set(e) <= APP_EVENT_KEYS
        AppSpeechEvent.model_validate(e)  # 应用的严格模型：多余字段、错误枚举都会抛错
    kinds = [e["event_type"] for e in out]
    assert "final" in kinds and kinds[-2:] == ["status", "end"]
    final = next(e for e in out if e["event_type"] == "final")
    assert final["source_kind"] == "upstream_live" and final["source_ref"].startswith("spk_")
    gap = next(e for e in out if e.get("status") == "disconnected")
    assert (gap["gap_start_ms"], gap["gap_end_ms"]) == (3000, 3400)
    assert len({e["event_id"] for e in out}) == len(out)
    # 丢掉的信息逐条可查
    assert any(d["event_type"] == EventType.SOURCE_POSITION.value for d in mapper.report.dropped)


def test_no_text_final_is_not_forwarded(tmp_path):
    mapper = AppEventMapper()
    out = [e for ev in lesson_events(tmp_path, None) for e in mapper.map(ev)]
    assert all(e["event_type"] != "final" for e in out)
    assert any("无转写文字" in d["reason"] for d in mapper.report.dropped)


def test_simulated_events_are_refused_even_with_override(tmp_path):
    events = lesson_events(tmp_path, FixedAsr(), data_origin="simulated")
    final = next(ev for ev in events if ev.event_type == EventType.TRANSCRIPT_FINAL)
    with pytest.raises(SyntheticRefused):
        AppEventMapper(source_kind="recorded_result").map(final)
