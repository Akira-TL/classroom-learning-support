from typing import Annotated

from fastapi import APIRouter, Depends

from ..classroom.auth import User, current_user, require_teacher
from ..classroom.storage import SQLiteStore
from .models import (
    ParentQuestion,
    PreviewRequest,
    PublishRequest,
    QuestionRequest,
    ReportPreview,
    ReportView,
    ResolveQuestion,
    RevokeRequest,
)
from .store import ReportStore


def reports_router(classrooms: SQLiteStore) -> APIRouter:
    router = APIRouter(tags=["家长反馈"])
    store = ReportStore(classrooms)

    @router.post("/api/classrooms/{cid}/parent-reports/preview", response_model=ReportPreview)
    def preview(cid: str, payload: PreviewRequest, user: Annotated[User, Depends(require_teacher)]) -> ReportPreview:
        return store.preview(cid, user.id, payload)

    @router.post("/api/classrooms/{cid}/parent-reports", response_model=ReportView)
    def publish(cid: str, payload: PublishRequest, user: Annotated[User, Depends(require_teacher)]) -> ReportView:
        return store.publish(cid, user.id, payload)

    @router.get("/api/classrooms/{cid}/parent-reports", response_model=list[ReportView])
    def listing(cid: str, user: Annotated[User, Depends(require_teacher)]) -> list[ReportView]:
        return store.list_reports(cid, user.id)

    @router.get("/api/parent-reports/{report_id}", response_model=ReportView)
    def read(report_id: str, user: Annotated[User, Depends(current_user)]) -> ReportView:
        return store.read(report_id, user)

    @router.post("/api/classrooms/{cid}/parent-reports/{report_id}/revoke", response_model=ReportView)
    def revoke(
        cid: str,
        report_id: str,
        payload: RevokeRequest,
        user: Annotated[User, Depends(require_teacher)],
    ) -> ReportView:
        return store.revoke(cid, report_id, user.id, payload)

    @router.post("/api/parent-reports/{report_id}/questions", response_model=ParentQuestion)
    def ask(
        report_id: str,
        payload: QuestionRequest,
        user: Annotated[User, Depends(current_user)],
    ) -> ParentQuestion:
        return store.ask(report_id, user, payload)

    @router.get("/api/classrooms/{cid}/parent-report-questions", response_model=list[ParentQuestion])
    def questions(cid: str, user: Annotated[User, Depends(require_teacher)]) -> list[ParentQuestion]:
        return store.questions(cid, user.id)

    @router.put("/api/classrooms/{cid}/parent-report-questions/{question_id}", response_model=ParentQuestion)
    def resolve(
        cid: str,
        question_id: str,
        payload: ResolveQuestion,
        user: Annotated[User, Depends(require_teacher)],
    ) -> ParentQuestion:
        return store.resolve(cid, user.id, question_id, payload)

    return router
