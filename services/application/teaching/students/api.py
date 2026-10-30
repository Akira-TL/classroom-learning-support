from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from ..classroom.auth import User, current_user, require_teacher
from ..classroom.storage import SQLiteStore
from .feedback import Feedback
from .models import (
    FeedbackRecord,
    HandleFeedback,
    ReportPreview,
    ReportSummary,
    ReportView,
    RevokeReport,
    StudentFeedbackRequest,
    StudentPublish,
    StudentPublishPreview,
)
from .publish import Publishing
from .store import FeedbackSource, StudentStore


def require_student(request: Request) -> User:
    user = current_user(request)
    if user.role != "student":
        raise HTTPException(403, "此操作需要学生本人身份")
    return user


def students_router(classroom_store: SQLiteStore) -> APIRouter:
    base = StudentStore(classroom_store)
    publish = Publishing(base)
    feedback = Feedback(base)
    router = APIRouter(prefix="/api", tags=["学生反馈"])

    @router.post("/classrooms/{cid}/student-reports/preview", response_model=ReportPreview)
    def preview(
        cid: str, payload: StudentPublishPreview, user: Annotated[User, Depends(require_teacher)]
    ) -> ReportPreview:
        return publish.preview(cid, user.id, payload)

    @router.post("/classrooms/{cid}/student-reports", response_model=ReportView)
    def issue(cid: str, payload: StudentPublish, user: Annotated[User, Depends(require_teacher)]) -> ReportView:
        return publish.publish(cid, user.id, payload)

    @router.get("/classrooms/{cid}/student-reports", response_model=list[ReportSummary])
    def teacher_reports(cid: str, user: Annotated[User, Depends(require_teacher)]) -> list[ReportSummary]:
        return base.list_teacher(cid, user.id)

    @router.post("/classrooms/{cid}/student-reports/{rid}/revoke", response_model=ReportSummary)
    def revoke(
        cid: str, rid: str, payload: RevokeReport, user: Annotated[User, Depends(require_teacher)]
    ) -> ReportSummary:
        return publish.revoke(cid, user.id, rid, payload)

    @router.get("/student-reports", response_model=list[ReportSummary])
    def student_reports(user: Annotated[User, Depends(require_student)]) -> list[ReportSummary]:
        return base.list_student(user.id)

    @router.get("/student-reports/{rid}", response_model=ReportView)
    def student_report(rid: str, user: Annotated[User, Depends(require_student)]) -> ReportView:
        return base.get(rid, user.id)

    @router.post("/student-reports/{rid}/feedback", response_model=FeedbackRecord)
    def submit(
        rid: str, payload: StudentFeedbackRequest, user: Annotated[User, Depends(require_student)]
    ) -> FeedbackRecord:
        return feedback.submit(rid, user.id, payload)

    @router.get("/student-reports/{rid}/feedback", response_model=list[FeedbackRecord])
    def student_feedback(rid: str, user: Annotated[User, Depends(require_student)]) -> list[FeedbackRecord]:
        return feedback.list_student(rid, user.id)

    @router.get("/classrooms/{cid}/student-feedback", response_model=list[FeedbackRecord])
    def teacher_feedback(cid: str, user: Annotated[User, Depends(require_teacher)]) -> list[FeedbackRecord]:
        return feedback.list_teacher(cid, user.id)

    @router.put("/classrooms/{cid}/student-feedback/{fid}", response_model=FeedbackRecord)
    def handle(
        cid: str, fid: str, payload: HandleFeedback, user: Annotated[User, Depends(require_teacher)]
    ) -> FeedbackRecord:
        return feedback.handle(cid, user.id, fid, payload)

    @router.get("/classrooms/{cid}/student-feedback/{fid}/source", response_model=FeedbackSource)
    def source(cid: str, fid: str, user: Annotated[User, Depends(require_teacher)]) -> FeedbackSource:
        return base.feedback_source(cid, user.id, fid)

    return router
