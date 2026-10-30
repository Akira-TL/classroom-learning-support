from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from ..classroom.auth import User, require_teacher
from ..classroom.storage import SQLiteStore
from .models import CreateInput, FinishInput, InputFrame, InputSession, InputState
from .store import InputStore


def inputs_router(classroom_store: SQLiteStore) -> APIRouter:
    store = InputStore(classroom_store)
    router = APIRouter(prefix="/api/classrooms/{cid}/input-sessions", tags=["仅采集传输诊断"])

    @router.post("", response_model=InputSession)
    def create(cid: str, payload: CreateInput, user: Annotated[User, Depends(require_teacher)]) -> InputSession:
        return store.create(cid, user.id, payload)

    @router.get("", response_model=list[InputSession])
    def listing(cid: str, user: Annotated[User, Depends(require_teacher)]) -> list[InputSession]:
        return store.list(cid, user.id)

    @router.get("/{sid}", response_model=InputSession)
    def get(cid: str, sid: str, user: Annotated[User, Depends(require_teacher)]) -> InputSession:
        return store.get(cid, user.id, sid)

    @router.post("/{sid}/frames", response_model=InputSession)
    def frame(cid: str, sid: str, payload: InputFrame, user: Annotated[User, Depends(require_teacher)]) -> InputSession:
        return store.frame(cid, user.id, sid, payload)

    @router.put("/{sid}/state", response_model=InputSession)
    def state(cid: str, sid: str, payload: InputState, user: Annotated[User, Depends(require_teacher)]) -> InputSession:
        return store.state(cid, user.id, sid, payload)

    @router.post("/{sid}/finish", response_model=InputSession)
    def finish(
        cid: str, sid: str, payload: FinishInput, user: Annotated[User, Depends(require_teacher)]
    ) -> InputSession:
        return store.finish(cid, user.id, sid, payload)

    @router.get("/{sid}/audio", response_model=None)
    def audio(cid: str, sid: str, user: Annotated[User, Depends(require_teacher)]) -> FileResponse:
        return FileResponse(
            store.audio_path(cid, user.id, sid),
            media_type="audio/wav",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @router.post("/{sid}/recover", response_model=InputSession)
    def recover(cid: str, sid: str, user: Annotated[User, Depends(require_teacher)]) -> InputSession:
        return store.recover(cid, user.id, sid)

    return router
