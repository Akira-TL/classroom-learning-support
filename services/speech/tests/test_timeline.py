import numpy as np
import pytest
import soundfile as sf

from classroom_speech.engines import AsrResult
from classroom_speech.events import EventType, Gap, Overlap, Reliability, SpeechEvent
from classroom_speech.pipeline import Session
from classroom_speech.spatial import ArrayConfig, tdoa
from classroom_speech.timeline import TimelineIndex, format_clock, parse_clock, read_clip

CFG = ArrayConfig()
SR = CFG.sample_rate


def ev(seq, kind, **kw):
    return SpeechEvent(session_id="ses_t", event_id=f"evt_{seq}", sequence=seq, event_type=kind, data_origin="simulated", **kw)


def final(seq, seg, a, b, text=None, status=None, overlap=(), revision=1, state=Reliability.USABLE):
    return ev(seq, EventType.TRANSCRIPT_FINAL if revision == 1 else EventType.TRANSCRIPT_REVISED, segment_id=seg,
              revision=revision, start_ms=a, end_ms=b, text=text, status=status, reliability_state=state,
              overlap=Overlap(present=bool(overlap), with_segments=list(overlap)))


def test_clock_parsing():
    assert parse_clock("00:10:23") == 623_000
    assert parse_clock("10:23.5") == 623_500
    assert parse_clock(12.25) == 12_250
    assert format_clock(593_000) == "00:09:53.000"
    assert format_clock(-25_000) == "-00:00:25.000"


def test_window_keeps_overlap_unrecognized_gap_and_unrecorded_states():
    events = [
        final(1, "seg_0001", 1000, 4000, text="甲"),
        final(2, "seg_0002", 3000, 6000, status="no_speech_recognized", overlap=["seg_0001"], state=Reliability.UNDETERMINED),
        final(3, "seg_0001", 1000, 4000, text="甲（修订）", revision=2),
        ev(4, EventType.STREAM_STATUS, status="gap", gap=Gap(start_ms=8000, end_ms=9000, reason="stream_dropout")),
        final(5, "seg_0003", 9500, 10000, text="丙"),
    ]
    tl = TimelineIndex.build(events, session_id="ses_t", sample_rate=SR, recorded_until_ms=11_000,
                             processed_until_ms=10_500, ended=False)
    w = tl.window(5000, before_ms=7000, after_ms=8000)  # [-2000, 13000)
    assert w["window"] == {"from_ms": 0, "to_ms": 11_000, "from_clock": "00:00:00.000", "to_clock": "00:00:11.000"}
    segs = {u["segment_id"]: u for u in w["utterances"]}
    assert segs["seg_0001"]["text"] == "甲（修订）" and segs["seg_0001"]["revision"] == 2
    assert segs["seg_0002"]["transcript_state"] == "unrecognized" and segs["seg_0002"]["overlap"]["present"]
    assert [segs[s]["relation"] for s in ("seg_0001", "seg_0002", "seg_0003")] == ["before", "spans_anchor", "after"]
    states = [(c["from_ms"], c["to_ms"], c["state"]) for c in w["coverage"]]
    assert states == [
        (-2000, 0, "not_recorded"), (0, 1000, "no_speech_detected"), (1000, 3000, "speech"), (3000, 4000, "overlap"),
        (4000, 6000, "speech"), (6000, 8000, "no_speech_detected"), (8000, 9000, "gap"), (9000, 9500, "no_speech_detected"),
        (9500, 10000, "speech"), (10000, 10500, "no_speech_detected"), (10500, 11000, "not_processed_yet"),
        (11000, 13000, "not_recorded"),
    ]
    # 覆盖区间无缝铺满请求窗口
    assert sum(c["to_ms"] - c["from_ms"] for c in w["coverage"]) == 15_000
    assert w["summary"]["unrecognized"] == 1 and w["summary"]["gap_ms"] == 1000 and not w["complete"]


def burst(rng, seconds, azimuth, gain=0.1):
    n = int(seconds * SR)
    x = rng.standard_normal(n) * (np.sin(np.linspace(0, 10 * np.pi, n)) > 0) * gain
    freqs = np.fft.rfftfreq(n, 1 / SR)
    y = np.fft.irfft(np.fft.rfft(x) * np.exp(-2j * np.pi * freqs * float(tdoa(azimuth, CFG))), n)
    return np.stack([x, y])


class SilentOnSecond:
    """第二段返回 None（模拟“无法识别”），其余返回固定文本。"""

    name = "fake"

    def __init__(self):
        self.calls = 0

    def transcribe(self, audio, sample_rate):
        self.calls += 1
        return None if self.calls == 2 else AsrResult(text=f"第{self.calls}句", engine=self.name)


def run_session(tmp_path):
    rng = np.random.default_rng(5)
    quiet = lambda s: 1e-4 * rng.standard_normal((2, int(s * SR)))  # noqa: E731
    first = np.concatenate([quiet(1.0), burst(rng, 1.5, 20.0), quiet(1.5), burst(rng, 1.2, -30.0), quiet(1.0)], axis=1)
    after_gap = np.concatenate([quiet(1.0), burst(rng, 1.5, 0.0), quiet(1.2)], axis=1)
    first, after_gap = first + quiet(first.shape[1] / SR), after_gap + quiet(after_gap.shape[1] / SR)  # 连续噪声底
    s = Session("ses_tl", tmp_path, asr=SilentOnSecond(), data_origin="simulated", capture_started_unix_ms=1_700_000_000_000)
    for chunk in np.array_split(first.astype(np.float32), 20, axis=1):
        s.push(chunk)
    s.mark_gap(2000)
    for chunk in np.array_split(after_gap.astype(np.float32), 10, axis=1):
        s.push(chunk)
    return s, first, after_gap


def test_session_timebase_survives_dropout_and_clip_is_sample_exact(tmp_path):
    s, first, after_gap = run_session(tmp_path)
    s.flush_raw()
    live = TimelineIndex.from_session(s)  # 录音进行中也能查
    assert live.recorded_until_ms == 6200 + 2000 + 3700
    gap = live.gaps[0]
    assert (gap["start_ms"], gap["end_ms"]) == (6200, 8200)
    clip, sr = read_clip(tmp_path / "raw.wav", 1000, 2500, channels="stereo")
    assert sr == SR and clip.shape == (24_000, 2)
    assert np.allclose(clip.T, first[:, SR : int(2.5 * SR)], atol=2 / 32768)  # 只差 16 位量化
    s.end()

    tl = TimelineIndex.from_session(s)
    starts = [u.start_ms for u in tl.utterances]
    assert len(starts) == 3
    # VAD 起点含 200 ms 回看余量；断流后那句仍落在补齐后的真实时间（9.2 s）附近
    assert [abs(a - b) <= 300 for a, b in zip(starts, [1000, 4000, 9200])] == [True] * 3
    assert [u.transcript_state for u in tl.utterances] == ["recognized", "unrecognized", "recognized"]
    w = tl.window(9200, before_ms=4000, after_ms=1000)
    assert "gap" in [c["state"] for c in w["coverage"]]
    assert [u["relation"] for u in w["utterances"]] == ["before", "spans_anchor"]

    rebuilt = TimelineIndex.from_archive(tmp_path)  # 服务重启后从存档重建，结果一致
    assert rebuilt.range(0, 12_000) == tl.range(0, 12_000)
    assert rebuilt.timebase["capture_started_unix_ms"] == 1_700_000_000_000
    assert s.to_session_ms(1_700_000_000_000 + 9_200) == 9200


def test_http_window_and_clip(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from classroom_speech import server

    s, *_ = run_session(tmp_path / "ses_tl")
    s.end()
    monkeypatch.setattr(server, "DATA_DIR", tmp_path)
    client = TestClient(server.app)
    # 不在内存里的会话：从存档目录回溯
    w = client.get("/v1/sessions/ses_tl/window", params={"at_ms": 9200, "before_ms": 30000, "after_ms": 60000}).json()
    assert w["window"]["from_ms"] == 0 and w["anchor"]["at_clock"] == "00:00:09.200"
    assert len(w["utterances"]) == 3 and w["audio"]["url"].endswith("/v1/audio/ses_tl/clip?from_ms=0&to_ms=11900")
    r = client.get("/v1/audio/ses_tl/clip", params={"from_ms": 1000, "to_ms": 2000})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    import io

    x, sr = sf.read(io.BytesIO(r.content))
    assert x.shape == (SR,) and sr == SR
    batch = client.post("/v1/sessions/ses_tl/windows", json=[{"anchor_id": "a1", "at_ms": 1000, "before_ms": 0, "after_ms": 3000},
                                                             {"anchor_id": "a2", "at_unix_ms": 1_700_000_009_200}]).json()
    assert [b["anchor_id"] for b in batch] == ["a1", "a2"] and batch[1]["anchor"]["at_ms"] == 9200
    seg = client.get(f"/v1/sessions/ses_tl/segments/{w['utterances'][0]['segment_id']}").json()
    assert len(seg["utterances"]) >= 1
    ref = w["utterances"][0]["audio_ref"][-1]["id"]
    assert client.get(f"/v1/audio/ses_tl/ref/{ref}").status_code == 200
    assert client.get("/v1/audio/ses_tl/ref/aud_ses_tl_..%2Fx").status_code == 404
    assert client.get("/v1/sessions/ses_nope/window", params={"at_ms": 1}).status_code == 404
