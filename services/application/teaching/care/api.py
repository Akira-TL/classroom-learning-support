from typing import Annotated

from fastapi import APIRouter, Depends

from ..classroom.auth import User, require_teacher
from ..classroom.storage import SQLiteStore
from .compare import compare
from .models import (
    CompareRequest,
    Comparison,
    Observation,
    ObservationInput,
    ObservationUpdate,
)
from .store import CareStore


def care_router(classrooms: SQLiteStore) -> APIRouter:
    store = CareStore(classrooms)
    router = APIRouter(prefix="/api", tags=["课堂学生信息"])

    @router.get("/classrooms/{cid}/care/observations", response_model=list[Observation])
    def observations(cid: str, user: Annotated[User, Depends(require_teacher)]) -> list[Observation]:
        with classrooms.connection() as db:
            return store.list_observations(db, user.id, cid)

    @router.post("/classrooms/{cid}/care/observations", response_model=Observation)
    def observe(cid: str, payload: ObservationInput, user: Annotated[User, Depends(require_teacher)]) -> Observation:
        return store.save_observation(cid, user.id, payload)

    @router.put("/classrooms/{cid}/care/observations/{oid}", response_model=Observation)
    def edit(cid: str, oid: str, payload: ObservationUpdate,
             user: Annotated[User, Depends(require_teacher)]) -> Observation:
        return store.save_observation(cid, user.id, payload, oid, payload.expected_revision)

    @router.post("/care/compare", response_model=Comparison)
    def comparison(payload: CompareRequest, user: Annotated[User, Depends(require_teacher)]) -> Comparison:
        with classrooms.connection() as db:
            return compare(db, store, user.id, payload)

    return router
