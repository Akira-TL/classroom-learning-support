from typing import Annotated

from fastapi import APIRouter, Depends

from ..audio.store import SpeechStore
from ..classroom.auth import User, require_teacher
from ..classroom.storage import SQLiteStore
from .models import CorrectionApply, CorrectionAssessment, CorrectionPreview, CorrectionResult
from .store import CorrectionStore


def corrections_router(classrooms: SQLiteStore, speech: SpeechStore) -> APIRouter:
    router = APIRouter(prefix="/api/classrooms/{cid}/corrections", tags=["教师纠错"])
    store = CorrectionStore(classrooms, speech)

    @router.post("/preview", response_model=CorrectionAssessment)
    def preview(
        cid: str, request: CorrectionPreview, user: Annotated[User, Depends(require_teacher)]
    ) -> CorrectionAssessment:
        return store.preview(cid, user.id, request)

    @router.post("", response_model=CorrectionResult)
    def apply(cid: str, request: CorrectionApply, user: Annotated[User, Depends(require_teacher)]) -> CorrectionResult:
        return store.apply(cid, user.id, request)

    return router
