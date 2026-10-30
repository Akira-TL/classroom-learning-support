from typing import Annotated

from fastapi import APIRouter, Depends

from ..classroom.auth import User, require_teacher
from ..classroom.storage import SQLiteStore
from .models import ExerciseAdoption, ExerciseGenerationResult, ExerciseRecord, ExerciseReview, GenerateExercises
from .store import ExerciseStore


def exercises_router(classroom_store: SQLiteStore) -> APIRouter:
    store = ExerciseStore(classroom_store)
    router = APIRouter(prefix="/api/classrooms/{classroom_id}/exercises", tags=["分层练习"])

    @router.get("", response_model=list[ExerciseGenerationResult])
    def listing(classroom_id: str, user: Annotated[User, Depends(require_teacher)]) -> list[ExerciseGenerationResult]:
        return store.list(classroom_id, user.id)

    @router.post("/generate", response_model=ExerciseGenerationResult)
    def generate(
        classroom_id: str,
        payload: GenerateExercises,
        user: Annotated[User, Depends(require_teacher)],
    ) -> ExerciseGenerationResult:
        return store.generate(classroom_id, user.id, payload)

    @router.put("/{record_id}/review", response_model=ExerciseRecord)
    def review(
        classroom_id: str,
        record_id: str,
        payload: ExerciseReview,
        user: Annotated[User, Depends(require_teacher)],
    ) -> ExerciseRecord:
        return store.update(classroom_id, user.id, record_id, payload)

    @router.put("/{record_id}/adoption", response_model=ExerciseRecord)
    def adoption(
        classroom_id: str,
        record_id: str,
        payload: ExerciseAdoption,
        user: Annotated[User, Depends(require_teacher)],
    ) -> ExerciseRecord:
        return store.update(classroom_id, user.id, record_id, payload)

    return router
