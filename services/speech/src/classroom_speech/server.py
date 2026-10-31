"""语音服务 HTTP / WebSocket 接口（speech.v0.1）。

    GET  /healthz
    GET  /v1/capabilities
    POST /v1/sessions                     创建会话；带 app_classroom_id 且配置了 SPEECH_APP_URL / SPEECH_INGEST_TOKEN 时，
                                          事件实时转成 app-draft-1 推给教学应用（见 app_bridge.py）
    GET  /v1/sessions/{id}/app            推送给教学应用的情况：已发送、重复、未发送及原因、错误
    WS   /v1/sessions/{id}/audio          输入：s16le 交错 PCM 二进制帧；文本帧 {"type":"end"}
    WS   /v1/sessions/{id}/events?after=N 输出：契约事件，按 sequence 续传
    GET  /v1/sessions/{id}/events?after=N 拉取版
    POST /v1/sessions/{id}/end            主动结束
    POST /v1/sessions/{id}/context        当前题目上下文（只用于识别候选排序与核验提示，不改写原文）
    POST /v1/sessions/{id}/gap            断流上报：{"duration_ms"} 在当前位置补静音；或 {"start_ms","end_ms"} 只标注
    GET  /v1/sessions/{id}/timebase       统一时间基准（会话毫秒 ↔ 墙钟）
    GET  /v1/sessions/{id}/timeline?from_ms=&to_ms=                 时间范围内的发言 / 说话人 / 方位 / 覆盖状态
    GET  /v1/sessions/{id}/window?at_ms=&before_ms=30000&after_ms=60000   以事件时间为中心的上下文回溯
    POST /v1/sessions/{id}/windows        多个事件锚点批量回溯 [{"anchor_id","at_ms"|"at_unix_ms","before_ms","after_ms"}]
    GET  /v1/sessions/{id}/segments/{seg} 单条发言（网页从发言跳到音频位置）
    GET  /v1/audio/{session_id}/raw       原音频（仅本机演示用，正式部署需加鉴权与过期）
    GET  /v1/audio/{session_id}/clip?from_ms=&to_ms=&channels=mic0|stereo   原始录音按时间切片，录音中也可用
    GET  /v1/audio/{session_id}/ref/{audio_ref_id}                  事件 audio_ref.id 对应的音轨（原始 / 去噪 / 分离）
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from .app_bridge import AppClient, AppForwarder
from .engines import FunAsrEngine, try_load
from .events import PROTOCOL_VERSION, SpeechEvent
from .pipeline import Session
from .spatial import ArrayConfig
from .stages import build_stages
from .timeline import TimelineIndex, clip_wav_bytes, resolve_audio_ref

DATA_DIR = Path(os.environ.get("SPEECH_DATA_DIR", "../../data/audio/speech"))
MIC_DISTANCE = float(os.environ.get("SPEECH_MIC_DISTANCE_M", "0.08"))
ASR_MODE = os.environ.get("SPEECH_ASR", "funasr")  # funasr | none
APP_URL = os.environ.get("SPEECH_APP_URL", "")  # 教学应用地址，如 http://127.0.0.1:8000
APP_TOKEN = os.environ.get("SPEECH_INGEST_TOKEN", "")  # 与应用侧同名环境变量一致，不写入仓库

app = FastAPI(title="classroom-speech", version=PROTOCOL_VERSION)
sessions: dict[str, Session] = {}
_asr = None


def asr_engine():
    global _asr
    if _asr is None and ASR_MODE == "funasr":
        _asr = try_load(FunAsrEngine, "FunASR") or False
    return _asr or None


class CreateSession(BaseModel):
    channels: int = 2
    sample_rate: int = 16000
    data_origin: str = "live"  # live | file_replay | simulated
    capture_started_unix_ms: int | None = None  # 采集端第 0 个样本的墙钟时间（推荐给，否则用首帧到达时间近似）
    app_classroom_id: str | None = None  # 教学应用里已创建的课堂标识（由应用侧私下交接）；给了才推送


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "asr": getattr(asr_engine(), "name", None), "sessions": len(sessions)}


@app.get("/v1/capabilities")
def capabilities() -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "audio_input": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": [1, 2], "frame_ms": 100, "max_frame_bytes": 65536},
        "transcript": {"partial": False, "final": True, "revision": False, "engine": getattr(asr_engine(), "name", None)},
        "position": {"azimuth": True, "requires": "两路同一时钟的原始通道", "mic_distance_m": MIC_DISTANCE, "anonymous_speaker": "按方位归并，仅会话内有效"},
        "overlap": {"detection": True, "separated_audio": "dsp_anchored_mask", "neural_separation": "可选，需本机安装 clearvoice"},
        "denoise": {"method": "spatial_spectral_dual_gate", "raw_audio_preserved": True},
        "identity": "不提供；声源只是线索",
        "timeline": {"timebase": "session_ms（样本计数）", "range_query": True, "context_window": {"default_before_ms": 30000, "default_after_ms": 60000},
                     "raw_clip": True, "persisted": "raw.wav + events.jsonl，服务重启后可回溯", "states": ["speech", "overlap", "no_speech_detected", "gap", "not_recorded", "not_processed_yet"]},
        "app_forwarding": {"protocol": "app-draft-1", "configured": bool(APP_URL and len(APP_TOKEN.strip()) >= 32),
                           "not_forwarded": ["source.position（方位）", "audio.available", "reliability_state", "diagnostics", "无文字的转写"]},
        "stages": build_stages().origin,  # 每个阶段当前跑的是优化版（contrib）还是基准
    }


@app.post("/v1/sessions")
def create_session(req: CreateSession) -> dict:
    if req.sample_rate != 16000:
        raise HTTPException(400, "当前版本只接受 16 kHz，请在采集端重采样")
    sid = f"ses_{uuid.uuid4().hex[:12]}"
    sessions[sid] = Session(sid, DATA_DIR / sid, asr=asr_engine(), data_origin=req.data_origin,
                            cfg=ArrayConfig(mic_distance_m=MIC_DISTANCE), capture_started_unix_ms=req.capture_started_unix_ms)
    sessions[sid].channels = req.channels
    forwarding = False
    if req.app_classroom_id:
        if not (APP_URL and len(APP_TOKEN.strip()) >= 32):
            raise HTTPException(400, "未配置 SPEECH_APP_URL 或 SPEECH_INGEST_TOKEN（至少 32 字符），无法推送到教学应用")
        if req.data_origin == "simulated":
            raise HTTPException(400, "模拟数据不能写入教学应用的可信入口")
        fwd = AppForwarder(AppClient(APP_URL, APP_TOKEN, req.app_classroom_id))
        sessions[sid].listeners.append(fwd)
        sessions[sid].app_forwarder = fwd
        forwarding = True
    return {"session_id": sid, "protocol_version": PROTOCOL_VERSION, "audio_origin_ms": 0, "channels": req.channels,
            "app_forwarding": forwarding}


@app.get("/v1/sessions/{sid}/app")
def app_forwarding(sid: str) -> dict:
    fwd = getattr(_get(sid), "app_forwarder", None)
    if fwd is None:
        return {"forwarding": False}
    r = fwd.mapper.report
    return {"forwarding": True, "stopped": fwd._stopped, "sent": r.sent, "duplicates": r.duplicates,
            "not_forwarded": r.dropped, "errors": r.errors}


def _get(sid: str) -> Session:
    if sid not in sessions:
        raise HTTPException(404, "会话不存在")
    return sessions[sid]


@app.get("/v1/sessions/{sid}/events")
def pull_events(sid: str, after: int = 0) -> list[SpeechEvent]:
    return _get(sid).events_after(after)


@app.post("/v1/sessions/{sid}/end")
def end_session(sid: str) -> SpeechEvent:
    s = _get(sid)
    if s.ended:
        return s.events[-1]
    return s.end()


class LessonContext(BaseModel):
    question: str | None = None
    expected_terms: list[str] = []


@app.post("/v1/sessions/{sid}/context")
def set_context(sid: str, req: LessonContext) -> dict:
    _get(sid).context = req.model_dump()
    return {"ok": True}


class GapReport(BaseModel):
    duration_ms: int | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    reason: str = "stream_dropout"


@app.post("/v1/sessions/{sid}/gap")
def report_gap(sid: str, req: GapReport) -> SpeechEvent:
    s = _get(sid)
    if s.ended:
        raise HTTPException(409, "会话已结束")
    if req.duration_ms is not None:
        if not 0 < req.duration_ms <= 600_000:
            raise HTTPException(400, "duration_ms 需在 (0, 600000]")
        return s.mark_gap(req.duration_ms, req.reason)
    if req.start_ms is None or req.end_ms is None or req.end_ms <= req.start_ms:
        raise HTTPException(400, "给 duration_ms，或给 start_ms < end_ms")
    return s.report_gap(req.start_ms, req.end_ms, req.reason)


def _timeline(sid: str) -> tuple[TimelineIndex, Path]:
    """活动会话直接读内存；不在内存（如服务重启）时从存档目录重建。"""
    if sid in sessions:
        s = sessions[sid]
        s.flush_raw()
        return TimelineIndex.from_session(s), s.archive_dir
    d = DATA_DIR / sid
    if sid.startswith("ses_") and "/" not in sid and (d / "events.jsonl").exists():
        return TimelineIndex.from_archive(d), d
    raise HTTPException(404, "会话不存在")


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@app.get("/v1/sessions/{sid}/timebase")
def get_timebase(sid: str) -> dict:
    tl, _ = _timeline(sid)
    return {**tl.timebase, "recorded_until_ms": tl.recorded_until_ms, "processed_until_ms": tl.processed_until_ms}


@app.get("/v1/sessions/{sid}/timeline")
def get_timeline(sid: str, request: Request, from_ms: int = 0, to_ms: int | None = None) -> dict:
    tl, _ = _timeline(sid)
    try:
        return tl.range(from_ms, tl.recorded_until_ms if to_ms is None else to_ms, audio_base_url=_base_url(request))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def _anchor_ms(sid: str, at_ms: int | None, at_unix_ms: int | None) -> int:
    if at_ms is not None:
        return at_ms
    if at_unix_ms is not None and sid in sessions:
        try:
            return sessions[sid].to_session_ms(at_unix_ms)
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
    if at_unix_ms is not None:
        tl, _ = _timeline(sid)
        if tl.timebase.get("capture_started_unix_ms") is None:
            raise HTTPException(409, "存档没有墙钟基准，请用 at_ms")
        return at_unix_ms - tl.timebase["capture_started_unix_ms"]
    raise HTTPException(400, "需要 at_ms（会话毫秒）或 at_unix_ms")


@app.get("/v1/sessions/{sid}/window")
def get_window(sid: str, request: Request, at_ms: int | None = None, at_unix_ms: int | None = None,
               before_ms: int = 30_000, after_ms: int = 60_000) -> dict:
    anchor = _anchor_ms(sid, at_ms, at_unix_ms)
    tl, _ = _timeline(sid)
    try:
        return tl.window(anchor, before_ms, after_ms, audio_base_url=_base_url(request))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class AnchorQuery(BaseModel):
    anchor_id: str | None = None  # Agent 侧事件 id，原样带回
    at_ms: int | None = None
    at_unix_ms: int | None = None
    before_ms: int = 30_000
    after_ms: int = 60_000


@app.post("/v1/sessions/{sid}/windows")
def get_windows(sid: str, request: Request, anchors: list[AnchorQuery]) -> list[dict]:
    tl, _ = _timeline(sid)
    out = []
    for q in anchors:
        try:
            w = tl.window(_anchor_ms(sid, q.at_ms, q.at_unix_ms), q.before_ms, q.after_ms, audio_base_url=_base_url(request))
        except ValueError as e:
            raise HTTPException(400, f"{q.anchor_id}: {e}") from e
        out.append({"anchor_id": q.anchor_id, **w})
    return out


@app.get("/v1/sessions/{sid}/segments/{seg_id}")
def get_segment(sid: str, seg_id: str, request: Request) -> dict:
    tl, _ = _timeline(sid)
    u = tl.segment(seg_id)
    if u is None:
        raise HTTPException(404, "发言不存在")
    return tl.range(u.start_ms, max(u.end_ms, u.start_ms + 1), audio_base_url=_base_url(request))


@app.get("/v1/audio/{sid}/clip")
def audio_clip(sid: str, from_ms: int, to_ms: int, channels: str = "mic0"):
    if channels not in ("mic0", "stereo"):
        raise HTTPException(400, "channels 只能是 mic0 或 stereo")
    if to_ms <= from_ms or to_ms - from_ms > 30 * 60_000:
        raise HTTPException(400, "需要 from_ms < to_ms，且单次不超过 30 分钟")
    tl, d = _timeline(sid)
    return Response(clip_wav_bytes(d / "raw.wav", from_ms, to_ms, channels), media_type="audio/wav",
                    headers={"X-Clip-From-Ms": str(max(from_ms, 0)), "X-Clip-To-Ms": str(min(to_ms, tl.recorded_until_ms))})


@app.get("/v1/audio/{sid}/ref/{ref_id}")
def audio_ref(sid: str, ref_id: str):
    _, d = _timeline(sid)
    path = resolve_audio_ref(d, sid, ref_id)
    if path is None:
        raise HTTPException(404, "音轨不存在")
    if path.name == "raw.wav" and sid in sessions and not sessions[sid].ended:
        raise HTTPException(409, "录音进行中，请用 /clip 按时间取片段")
    return FileResponse(path, media_type="audio/wav")


@app.get("/v1/audio/{sid}/raw")
def raw_audio(sid: str):
    s = _get(sid)
    if not s.ended:
        raise HTTPException(409, "会话结束后才能整段回听")
    return FileResponse(s.archive_dir / "raw.wav", media_type="audio/wav")


@app.websocket("/v1/sessions/{sid}/audio")
async def audio_ws(ws: WebSocket, sid: str) -> None:
    s = sessions.get(sid)
    await ws.accept()
    if s is None or s.ended:
        await ws.close(code=4404)
        return
    try:
        while True:
            msg = await ws.receive()
            if msg.get("bytes"):
                await asyncio.to_thread(s.push_pcm, msg["bytes"], getattr(s, "channels", 2))
            elif msg.get("text"):
                if json.loads(msg["text"]).get("type") == "end":
                    await asyncio.to_thread(s.end)
                    break
            elif msg.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass  # 音频断开不结束会话：可重连续传，缺失区间由客户端上报或超时判定


@app.websocket("/v1/sessions/{sid}/events")
async def events_ws(ws: WebSocket, sid: str, after: int = 0) -> None:
    s = sessions.get(sid)
    await ws.accept()
    if s is None:
        await ws.close(code=4404)
        return
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    listener = lambda ev: loop.call_soon_threadsafe(queue.put_nowait, ev)  # noqa: E731
    s.listeners.append(listener)
    try:
        last = after
        for ev in s.events_after(after):
            await ws.send_text(ev.model_dump_json(by_alias=True, exclude_none=True))
            last = ev.sequence
        while True:
            ev = await queue.get()
            if ev.sequence <= last:
                continue
            await ws.send_text(ev.model_dump_json(by_alias=True, exclude_none=True))
            last = ev.sequence
            if ev.event_type == "session.ended":
                break
    except WebSocketDisconnect:
        pass
    finally:
        s.listeners.remove(listener)
