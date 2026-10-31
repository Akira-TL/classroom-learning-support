"""外部标签批次绑定原始音频，无须存在转写发言。"""

import io
import wave
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ...audio.media import AudioAsset, AudioStore
from ...classroom.auth import User, require_teacher
from ...classroom.storage import SQLiteStore, StoreError
from .models import TagBatch
from .store import TagStore


def batch_audio_router(classrooms: SQLiteStore) -> APIRouter:
    tags, audio = TagStore(classrooms), AudioStore(classrooms.path)
    router = APIRouter(prefix="/classrooms/{cid}/care/tag-batches", tags=["标签来源音频"])

    def batch(cid: str, bid: str, teacher: str) -> TagBatch:
        with classrooms.connection() as db:
            records = tags.listing(db, teacher, cid)
            record = next((item for item in records if item.id == bid), None)
            if record is None:
                raise StoreError(404, "标签批次不存在")
            return record

    @router.post("/{bid}/audio", response_model=AudioAsset)
    async def upload(cid: str, bid: str, request: Request,
                     user: Annotated[User, Depends(require_teacher)]) -> AudioAsset:
        record = batch(cid, bid, user.id)
        if request.headers.get("content-type", "").split(";")[0] not in {"audio/wav", "audio/x-wav"}:
            raise HTTPException(415, "标签来源音频目前只接收PCM WAV，请先转换为WAV后上传")
        content = bytearray()
        async for block in request.stream():
            if len(content) + len(block) > audio.max_bytes:
                raise HTTPException(413, "音频超过20MB")
            content.extend(block)
        try:
            with wave.open(io.BytesIO(content), "rb") as wav:
                duration_ms = wav.getnframes() * 1000 // wav.getframerate()
        except (wave.Error, EOFError, ZeroDivisionError):
            raise HTTPException(422, "音频不是有效的PCM WAV") from None
        latest = batch(cid, bid, user.id)
        if latest.revision != record.revision or latest.session_id != record.session_id:
            raise HTTPException(409, "上传期间标签来源已变化，请刷新后重试")
        if any(tag.end_ms > duration_ms for tag in latest.tags) or any(
            item.end_ms > duration_ms for item in latest.transcripts
        ):
            raise HTTPException(422, "标签或转写时间超出音频时长，请核对源文件与时间基准")
        # AudioStore 使用课堂和会话唯一键，拒绝原声覆盖；修改源文件须创建新会话与来源版本。
        return audio.save(cid, record.session_id, bytes(content), source="provided_tag_batch_audio")

    @router.get("/{bid}/audio", response_model=None)
    def original(cid: str, bid: str, user: Annotated[User, Depends(require_teacher)]) -> FileResponse:
        record = batch(cid, bid, user.id)
        _, path = audio.get(cid, record.session_id)
        return FileResponse(path, media_type="audio/wav", headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })

    return router
