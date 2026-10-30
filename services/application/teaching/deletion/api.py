from typing import Annotated

from fastapi import APIRouter, Depends

from ..classroom.auth import User, require_teacher
from ..classroom.storage import SQLiteStore
from .models import DeleteClassroom, DeletionView
from .store import DeletionStore


def deletion_router(classroom_store: SQLiteStore) -> APIRouter:
    store = DeletionStore(classroom_store)
    router = APIRouter(prefix="/api", tags=["课堂删除"])

    @router.post("/classrooms/{cid}/deletion", response_model=DeletionView)
    def create(cid: str, payload: DeleteClassroom, user: Annotated[User, Depends(require_teacher)]) -> DeletionView:
        return store.create(cid, user.id, payload)

    @router.get("/classroom-deletions/{identity}", response_model=DeletionView)
    def get(identity: str, user: Annotated[User, Depends(require_teacher)]) -> DeletionView:
        return store.get(identity, user.id)

    @router.post("/classroom-deletions/{identity}/retry", response_model=DeletionView)
    def retry(identity: str, user: Annotated[User, Depends(require_teacher)]) -> DeletionView:
        return store.retry(identity, user.id)

    return router
