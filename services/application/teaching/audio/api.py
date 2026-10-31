"""受课堂授权保护的模拟语音事件及教师核验接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse

from ..classroom.auth import User, require_teacher
from ..classroom.storage import SQLiteStore, StoreError
from ..integration.tracks import fetch_track
from ..models import StrictModel
from .media import AudioAsset, AudioStore
from .models import ReviewRequest, SpeechEvent, Utterance
from .store import SpeechConflict, SpeechStore


class EventReceipt(StrictModel):
    created: bool


def speech_router(classroom_store: SQLiteStore, speech_store: SpeechStore) -> APIRouter:
    router = APIRouter(prefix="/api/classrooms/{classroom_id}/speech", tags=["语音与核验"])
    audio_store = AudioStore(classroom_store.path)

    @router.post("/events", response_model=EventReceipt)
    def receive(
        classroom_id: str,
        payload: SpeechEvent,
        user: Annotated[User, Depends(require_teacher)],
    ) -> EventReceipt:
        classroom_store.get_classroom(user.id, classroom_id)
        if payload.source_kind == "upstream_live":
            raise HTTPException(409, "当前入口仅支持模拟或已记录结果，真实服务须通过受控适配层接入")
        try:
            return EventReceipt(created=speech_store.receive(classroom_id, payload))
        except SpeechConflict as error:
            raise HTTPException(409, str(error)) from None

    @router.get("/events", response_model=list[SpeechEvent])
    def events(classroom_id: str, user: Annotated[User, Depends(require_teacher)]) -> list[SpeechEvent]:
        classroom_store.get_classroom(user.id, classroom_id)
        return speech_store.events(classroom_id)

    @router.get("/timeline", response_model=list[Utterance])
    def timeline(classroom_id: str, user: Annotated[User, Depends(require_teacher)]) -> list[Utterance]:
        classroom_store.get_classroom(user.id, classroom_id)
        result = []
        for item in speech_store.timeline(classroom_id):
            try:
                asset, _ = audio_store.get(classroom_id, item.session_id)
                available = item.end_ms <= asset.duration_ms
            except StoreError as error:
                if error.status != 404:
                    raise
                available = bool(item.native_event and item.native_event.audio_ref)
            result.append(item.model_copy(update={"audio_available": available}))
        return result

    @router.post("/{session_id}/audio", response_model=AudioAsset)
    async def upload_audio(
        classroom_id: str,
        session_id: str,
        request: Request,
        user: Annotated[User, Depends(require_teacher)],
    ) -> AudioAsset:
        classroom_store.get_classroom(user.id, classroom_id)
        if not any(item.session_id == session_id for item in speech_store.events(classroom_id)):
            raise HTTPException(404, "会话不存在，请先建立模拟或真实采集会话")
        if request.headers.get("content-type", "").split(";")[0] not in {"audio/wav", "audio/x-wav"}:
            raise HTTPException(415, "只接收PCM WAV音频")
        content = bytearray()
        async for block in request.stream():
            if len(content) + len(block) > audio_store.max_bytes:
                raise HTTPException(413, "音频超过20MB")
            content.extend(block)
        return audio_store.save(classroom_id, session_id, bytes(content))

    @router.put("/{session_id}/{segment_id}/review", response_model=Utterance)
    def review(
        classroom_id: str,
        session_id: str,
        segment_id: str,
        payload: ReviewRequest,
        user: Annotated[User, Depends(require_teacher)],
    ) -> Utterance:
        classroom = classroom_store.get_classroom(user.id, classroom_id)
        if payload.student_alias is not None and payload.student_alias not in classroom.students:
            raise HTTPException(422, "所选学生不在本课堂名单中")
        if payload.question_id is not None and payload.question_id not in {item.id for item in classroom.questions}:
            raise HTTPException(422, "所选题目不属于本课堂")
        try:
            return speech_store.review(classroom_id, session_id, segment_id, user.id, payload)
        except SpeechConflict as error:
            raise HTTPException(409, str(error)) from None
        except KeyError:
            raise HTTPException(404, "发言片段不存在") from None

    @router.get("/{session_id}/{segment_id}/audio", response_model=None)
    def audio(
        classroom_id: str,
        session_id: str,
        segment_id: str,
        user: Annotated[User, Depends(require_teacher)],
    ) -> Response:
        classroom_store.get_classroom(user.id, classroom_id)
        item = next(
            (
                item
                for item in speech_store.timeline(classroom_id)
                if item.session_id == session_id and item.segment_id == segment_id
            ),
            None,
        )
        if item is None:
            raise HTTPException(404, "发言片段不存在")
        asset, path = audio_store.get(classroom_id, session_id)
        if item.end_ms > asset.duration_ms:
            raise HTTPException(409, "发言时间超出已归档音频范围，需核对时间基准")
        return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @router.get("/{session_id}/{segment_id}/tracks/{ref_id}", response_model=None)
    def track(
        classroom_id: str, session_id: str, segment_id: str, ref_id: str,
        user: Annotated[User, Depends(require_teacher)],
    ) -> Response:
        classroom_store.get_classroom(user.id, classroom_id)
        item = next((item for item in speech_store.timeline(classroom_id)
                     if item.session_id == session_id and item.segment_id == segment_id), None)
        if not item or not item.native_event or not any(ref.id == ref_id for ref in item.native_event.audio_ref):
            raise HTTPException(404, "该课堂发言未引用此音轨")
        return fetch_track(session_id, ref_id)

    return router
