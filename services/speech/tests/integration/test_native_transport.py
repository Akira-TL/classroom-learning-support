"""传输行为校验；不以测试帧证明模型识别或语音分离质量。"""

import base64
from dataclasses import dataclass, field

import pytest

from classroom_speech.events import AudioRef, EventType, Reliability, SpeechEvent
from classroom_speech.transport.frames import FrameConflict, FrameReceiver, InputFrame
from classroom_speech.transport.native_bridge import Envelope, require_real


@dataclass
class Recorder:
    ended: bool = False
    writes: list[bytes] = field(default_factory=list)

    def push_pcm(self, pcm: bytes, channels: int = 2) -> None:
        self.writes.append(pcm)


def frame(sequence: int = 0, start: int = 0, pcm: bytes = b"\x01\x00\x02\x00") -> InputFrame:
    return InputFrame(sequence=sequence, start_sample=start, frame_count=2,
                      pcm_base64=base64.b64encode(pcm).decode())


def test_duplicate_frames_write_once_even_after_end() -> None:
    recorder = Recorder()
    receiver = FrameReceiver(recorder, 1)
    assert receiver.accept(frame()).received_samples == 2
    recorder.ended = True
    assert receiver.accept(frame()).expected_sequence == 1
    assert recorder.writes == [b"\x01\x00\x02\x00"]
    with pytest.raises(FrameConflict):
        receiver.accept(frame(1, 2))


def test_changed_duplicate_and_out_of_order_do_not_write() -> None:
    recorder = Recorder()
    receiver = FrameReceiver(recorder, 1)
    receiver.accept(frame())
    with pytest.raises(FrameConflict):
        receiver.accept(frame(pcm=b"\x00\x00\x00\x00"))
    with pytest.raises(FrameConflict):
        receiver.accept(frame(2, 2))
    with pytest.raises(FrameConflict):
        receiver.accept(frame(1, 4))
    assert len(recorder.writes) == 1


def test_stereo_frame_requires_actual_interleaved_channel_bytes() -> None:
    recorder = Recorder()
    receiver = FrameReceiver(recorder, 2)
    with pytest.raises(ValueError):
        receiver.accept(frame())
    stereo = frame(pcm=b"\x01\x00\x02\x00\x03\x00\x04\x00")
    assert receiver.accept(stereo).received_samples == 2
    assert recorder.writes == [base64.b64decode(stereo.pcm_base64)]


def test_native_envelope_preserves_failed_transcript_and_audio_offsets() -> None:
    event = SpeechEvent(session_id="ses_test", event_id="evt_1", sequence=1,
                        event_type=EventType.TRANSCRIPT_FINAL, segment_id="seg_1", revision=1,
                        reliability_state=Reliability.FAILED, status="asr_unavailable",
                        audio_ref=[AudioRef(id="processed", kind="separated", offset_ms=2400)],
                        diagnostics={"math_review_reasons": ["分母待核验"]})
    require_real(event)
    saved = Envelope.model_validate_json(Envelope(classroom_id="class_1", event=event).model_dump_json())
    assert saved.event == event
    assert saved.event.text is None
    assert saved.event.audio_ref[0].offset_ms == 2400
    with pytest.raises(ValueError):
        require_real(event.model_copy(update={"data_origin": "simulated"}))
    with pytest.raises(ValueError):
        require_real(event.model_copy(update={"diagnostics": {"engine": "oracle_script_by_time"}}))
