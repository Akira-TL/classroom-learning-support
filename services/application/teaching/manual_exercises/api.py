from typing import Annotated

from fastapi import APIRouter, Depends

from ..classroom.auth import User, require_teacher
from ..classroom.storage import SQLiteStore
from .models import CreateManualExercises, ManualAdoption, ManualExerciseRecord, ManualReview
from .store import ManualExerciseStore


def manual_exercises_router(classroom_store: SQLiteStore) -> APIRouter:
    store = ManualExerciseStore(classroom_store)
    router = APIRouter(prefix="/api/classrooms/{classroom_id}/manual-exercises", tags=["人工通用课堂练习"])

    @router.post("", response_model=ManualExerciseRecord)
    def create(
        classroom_id: str, payload: CreateManualExercises, user: Annotated[User, Depends(require_teacher)]
    ) -> ManualExerciseRecord:
        return store.create(classroom_id, user.id, payload)

    @router.get("", response_model=list[ManualExerciseRecord])
    def listing(classroom_id: str, user: Annotated[User, Depends(require_teacher)]) -> list[ManualExerciseRecord]:
        return store.list(classroom_id, user.id)

    @router.put("/{record_id}/review", response_model=ManualExerciseRecord)
    def review(
        classroom_id: str, record_id: str, payload: ManualReview, user: Annotated[User, Depends(require_teacher)]
    ) -> ManualExerciseRecord:
        return store.update(classroom_id, user.id, record_id, payload)

    @router.put("/{record_id}/adoption", response_model=ManualExerciseRecord)
    def adoption(
        classroom_id: str, record_id: str, payload: ManualAdoption, user: Annotated[User, Depends(require_teacher)]
    ) -> ManualExerciseRecord:
        return store.update(classroom_id, user.id, record_id, payload)

    return router
