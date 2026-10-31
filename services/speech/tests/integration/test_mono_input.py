"""单声道的内部复制不能产生阵列定位或说话人区分。"""

from unittest.mock import Mock

import numpy as np
import pytest
from classroom_speech.events import EventType, Reliability
from classroom_speech.pipeline import Session


def test_mono_skips_spatial_algorithms_and_only_reports_unknown_source(tmp_path):
    session = Session("ses_mono", tmp_path, channels=1)
    session.stages.localize = Mock(side_effect=AssertionError("单声道不能运行阵列定位"))
    session.stages.separate = Mock(side_effect=AssertionError("单声道不能运行空间分离"))
    session.speakers.assign = Mock(side_effect=AssertionError("单声道不能用方位分配说话人"))
    raw = np.sin(np.arange(16000) * 0.05).astype(np.float32)
    try:
        events = session.process_segment(np.stack([raw, raw]), 16000)
        position = next(event for event in events if event.event_type == EventType.SOURCE_POSITION)
        assert position.status == "mono_position_unavailable"
        assert position.reliability_state == Reliability.UNDETERMINED
        assert len(position.sources) == 1
        source = position.sources[0]
        assert source.kind == "anon_speaker" and source.value == "unknown"
        assert source.reliability_state == Reliability.UNDETERMINED
        assert not source.rebind_hint
        transcript = next(event for event in events if event.event_type == EventType.TRANSCRIPT_FINAL)
        assert transcript.text is None and transcript.status == "asr_unavailable"
        assert [reference.kind for reference in transcript.audio_ref] == ["raw"]
        assert (transcript.start_ms, transcript.end_ms) == (1000, 2000)
        assert transcript.source_ref == position.source_ref
    finally:
        session.end()


def test_pcm_records_actual_channel_count_and_refuses_midstream_change(tmp_path):
    session = Session("ses_channel_count", tmp_path)
    try:
        session.push_pcm(bytes(3200), channels=1)
        assert session.channels == 1
        assert session.timebase()["input_channels"] == 1
        assert session.timebase()["stored_channels"] == 2
        with pytest.raises(ValueError, match="改变"):
            session.push_pcm(bytes(3200), channels=2)
        with pytest.raises(ValueError, match="双声道"):
            session.push_pcm(bytes(3200), channels=3)
    finally:
        session.end()


def test_real_stereo_position_keeps_azimuth_and_tracking(tmp_path):
    session = Session("ses_stereo", tmp_path, channels=2)
    raw = np.zeros(16000, dtype=np.float32)
    try:
        events = session._emit_segment("seg_real", raw, 25.0, 0, 1000, [], "raw", 0.9)
        position = next(event for event in events if event.event_type == EventType.SOURCE_POSITION)
        azimuth = next(source for source in position.sources if source.kind == "azimuth")
        assert azimuth.value == 25.0 and azimuth.reliability_state == Reliability.USABLE
        assert any(source.kind == "anon_speaker" and source.value != "unknown" for source in position.sources)
    finally:
        session.end()
