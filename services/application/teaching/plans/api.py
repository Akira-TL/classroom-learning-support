from typing import Annotated

from fastapi import APIRouter, Depends

from ..classroom.auth import User, require_teacher
from ..classroom.storage import SQLiteStore
from .models import GeneratePlan, PlanAdoption, PlanGenerationResult, PlanRecord, PlanReview
from .store import PlanStore


def plans_router(classroom_store: SQLiteStore) -> APIRouter:
    store = PlanStore(classroom_store)
    router = APIRouter(prefix="/api/classrooms/{classroom_id}/plans", tags=["提问与下一课安排"])

    @router.get("", response_model=list[PlanGenerationResult])
    def listing(classroom_id: str, user: Annotated[User, Depends(require_teacher)]) -> list[PlanGenerationResult]:
        return store.list(classroom_id, user.id)

    @router.post("/generate", response_model=PlanGenerationResult)
    def generate(
        classroom_id: str,
        payload: GeneratePlan,
        user: Annotated[User, Depends(require_teacher)],
    ) -> PlanGenerationResult:
        return store.generate(classroom_id, user.id, payload)

    @router.put("/{record_id}/review", response_model=PlanRecord)
    def review(
        classroom_id: str,
        record_id: str,
        payload: PlanReview,
        user: Annotated[User, Depends(require_teacher)],
    ) -> PlanRecord:
        return store.update(classroom_id, user.id, record_id, payload)

    @router.put("/{record_id}/adoption", response_model=PlanRecord)
    def adoption(
        classroom_id: str,
        record_id: str,
        payload: PlanAdoption,
        user: Annotated[User, Depends(require_teacher)],
    ) -> PlanRecord:
        return store.update(classroom_id, user.id, record_id, payload)

    return router
