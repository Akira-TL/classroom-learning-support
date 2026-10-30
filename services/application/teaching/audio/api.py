"""受课堂授权保护的模拟语音事件及教师核验接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..classroom.auth import User, require_teacher
from ..classroom.storage import SQLiteStore
from ..models import StrictModel
from .models import SpeechEvent, Utterance
from .store import SpeechConflict, SpeechStore


class EventReceipt(StrictModel):
    created: bool


def speech_router(classroom_store: SQLiteStore, speech_store: SpeechStore) -> APIRouter:
    router = APIRouter(prefix="/api/classrooms/{classroom_id}/speech", tags=["语音与核验"])

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
        return speech_store.timeline(classroom_id)

    return router
