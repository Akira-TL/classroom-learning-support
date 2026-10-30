"""令牌仅允许写入归一化结果，不授予课堂读取或教学发布权限。"""

import os
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException

from ..audio.store import SpeechConflict, SpeechStore
from ..classroom.auth import User, require_teacher
from ..classroom.storage import SQLiteStore
from .models import SpeechEndpointStatus, SpeechIngest, SpeechReceipt


def speech_ingest_router(classrooms: SQLiteStore, speech: SpeechStore) -> APIRouter:
    if classrooms.path.resolve() != speech.path.resolve():
        raise ValueError("可信语音结果与课堂须使用同一事务数据库")
    router = APIRouter(prefix="/api/integrations/speech", tags=["可信语音结果接入"])

    @router.get("/status", response_model=SpeechEndpointStatus)
    def status(_user: Annotated[User, Depends(require_teacher)]) -> SpeechEndpointStatus:
        enabled = len(os.getenv("SPEECH_INGEST_TOKEN", "").strip()) >= 32
        return SpeechEndpointStatus(
            endpoint_enabled=enabled,
            message="接入凭证已配置，但不代表供应方接口、设备或真实音频流程已验证。"
            if enabled
            else "接入凭证未配置或不足32字符，可信结果入口不可用；真实语音服务尚未验证。",
        )

    @router.post("/events", response_model=SpeechReceipt)
    def ingest(
        payload: SpeechIngest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> SpeechReceipt:
        token = os.getenv("SPEECH_INGEST_TOKEN", "").strip()
        if len(token) < 32:
            raise HTTPException(503, "语音结果接入凭证未配置或不符合长度要求")
        scheme, _, supplied = (authorization or "").partition(" ")
        matches = secrets.compare_digest(supplied.strip().encode(), token.encode())
        if scheme.lower() != "bearer" or not matches:
            raise HTTPException(401, "语音结果接入鉴权失败", headers={"WWW-Authenticate": "Bearer"})
        if payload.event.source_kind == "synthetic":
            raise HTTPException(409, "可信接入只接受真实上游或已记录结果；模拟事件请使用教师模拟入口")
        with classrooms.connection() as db:
            if not db.execute("SELECT 1 FROM classrooms WHERE id=?", (payload.classroom_id,)).fetchone():
                raise HTTPException(404, "课堂不存在")
        try:
            return SpeechReceipt(created=speech.receive(payload.classroom_id, payload.event))
        except SpeechConflict as error:
            raise HTTPException(409, str(error)) from None

    return router
