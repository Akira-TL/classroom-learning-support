"""服务器转发实际样本；凭证只留在语音服务和应用之间。"""

import os

import httpx
from pydantic import BaseModel, ValidationError

from ..classroom.storage import StoreError
from .models import InputFrame, InputSession


class CreatedSession(BaseModel):
    session_id: str
    app_forwarding: bool
    recognizer_connected: bool = False


class FrameReceipt(BaseModel):
    expected_sequence: int
    received_samples: int


class ForwardingStatus(BaseModel):
    forwarding: bool = False
    stopped: bool = False
    pending: int = 0


def request(method: str, path: str, content: str | None = None) -> httpx.Response:
    base = os.getenv("SPEECH_SERVICE_URL", "http://127.0.0.1:8765").rstrip("/")
    try:
        result = httpx.request(
            method, f"{base}{path}", content=content,
            headers={"Content-Type": "application/json"}, timeout=120,
        )
        result.raise_for_status()
        return result
    except httpx.HTTPError:
        raise StoreError(503, "语音服务未确认接收；本机游标不前移，可重试同一帧") from None


class SessionRequest(BaseModel):
    channels: int
    sample_rate: int
    data_origin: str
    app_classroom_id: str


def create(session: InputSession) -> str:
    if session.sample_rate != 16000:
        raise StoreError(422, "真实语音服务需要16kHz输入，请使用16kHz文件或麦克风采样")
    payload = SessionRequest(
        channels=session.channels, sample_rate=session.sample_rate,
        data_origin="live" if session.input_mode == "microphone" else "file_replay",
        app_classroom_id=session.classroom_id,
    )
    try:
        response = CreatedSession.model_validate_json(
            request("POST", "/v1/sessions", payload.model_dump_json()).content,
        )
    except ValidationError:
        raise StoreError(503, "语音服务创建响应格式不符，未开始音频发送") from None
    if not response.app_forwarding:
        raise StoreError(503, "语音服务未启用应用结果转发，不能开始教学识别")
    if not response.recognizer_connected:
        raise StoreError(503, "语音服务尚未加载真实识别引擎，不能声明已连接识别")
    return response.session_id


def frame(session: InputSession, payload: InputFrame) -> None:
    response = request("POST", f"/v1/sessions/{session.speech_session_id}/frames", payload.model_dump_json())
    try:
        receipt = FrameReceipt.model_validate_json(response.content)
    except ValidationError:
        raise StoreError(503, "语音服务帧确认格式不符，未前移本机样本游标") from None
    if receipt.received_samples != payload.start_sample + payload.frame_count:
        raise StoreError(409, "语音服务样本游标不符，停止转发以避免音频错位")
    if receipt.expected_sequence != payload.sequence + 1:
        raise StoreError(409, "语音服务帧序号不符，停止转发以避免重复")


def finish(session: InputSession) -> None:
    request("POST", f"/v1/sessions/{session.speech_session_id}/end")


def forwarding(session: InputSession) -> bool:
    response = request("GET", f"/v1/sessions/{session.speech_session_id}/app")
    try:
        status = ForwardingStatus.model_validate_json(response.content)
    except ValidationError:
        raise StoreError(503, "语音结果转发状态格式不符，不能声明接入完成") from None
    if not status.forwarding or status.stopped:
        raise StoreError(503, "语音结果转发已停止，请检查语音服务；不能声明接入完成")
    return status.pending > 0
