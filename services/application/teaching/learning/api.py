from typing import Annotated

from fastapi import APIRouter, Depends

from ..audio.store import SpeechStore
from ..classroom.auth import User, require_teacher
from ..classroom.storage import SQLiteStore
from .models import EvidenceRecord, EvidenceReview, GenerateEvidence, GenerationResult
from .store import EvidenceStore


def learning_router(classroom_store: SQLiteStore, speech_store: SpeechStore) -> APIRouter:
    if classroom_store.path.resolve() != speech_store.path.resolve():
        raise ValueError("学习证据与课堂语音须使用同一事务数据库")
    evidence = EvidenceStore(classroom_store)
    router = APIRouter(prefix="/api/classrooms/{classroom_id}/evidence", tags=["学习证据"])

    @router.get("", response_model=list[GenerationResult])
    def listing(classroom_id: str, user: Annotated[User, Depends(require_teacher)]) -> list[GenerationResult]:
        return evidence.list(classroom_id, user.id)

    @router.post("/generate", response_model=GenerationResult)
    def generate(
        classroom_id: str,
        request: GenerateEvidence,
        user: Annotated[User, Depends(require_teacher)],
    ) -> GenerationResult:
        classroom_store.get_classroom(user.id, classroom_id)
        return evidence.generate(classroom_id, user.id, request)

    @router.put("/{evidence_id}/review", response_model=EvidenceRecord)
    def review(
        classroom_id: str,
        evidence_id: str,
        request: EvidenceReview,
        user: Annotated[User, Depends(require_teacher)],
    ) -> EvidenceRecord:
        return evidence.review(classroom_id, user.id, evidence_id, request)

    return router
