from typing import Annotated

from fastapi import APIRouter, Depends

from ...classroom.auth import User, require_teacher
from ...classroom.storage import SQLiteStore
from ..models import CompareRequest
from .audio import batch_audio_router
from .compare import compare_tags
from .models import TagBatch, TagComparison, TagImport, TagUpdate
from .store import TagStore


def tag_router(classrooms: SQLiteStore) -> APIRouter:
    store = TagStore(classrooms)
    router = APIRouter(prefix="/api", tags=["外部行为声音标注"])
    router.include_router(batch_audio_router(classrooms))

    @router.get("/classrooms/{cid}/care/tag-batches", response_model=list[TagBatch])
    def listing(cid: str, user: Annotated[User, Depends(require_teacher)]) -> list[TagBatch]:
        with classrooms.connection() as db:
            return store.listing(db, user.id, cid)

    @router.post("/classrooms/{cid}/care/tag-batches", response_model=TagBatch)
    def create(cid: str, payload: TagImport, user: Annotated[User, Depends(require_teacher)]) -> TagBatch:
        return store.save(cid, user.id, payload)

    @router.put("/classrooms/{cid}/care/tag-batches/{bid}", response_model=TagBatch)
    def update(cid: str, bid: str, payload: TagUpdate, user: Annotated[User, Depends(require_teacher)]) -> TagBatch:
        return store.save(cid, user.id, payload, bid, payload.expected_revision)

    @router.post("/care/tag-comparison", response_model=TagComparison)
    def compare(payload: CompareRequest, user: Annotated[User, Depends(require_teacher)]) -> TagComparison:
        with classrooms.connection() as db:
            return compare_tags(db, store, user.id, payload)

    return router
