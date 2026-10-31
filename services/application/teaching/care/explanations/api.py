from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ...classroom.auth import User, current_user, require_teacher
from ...classroom.classrooms import Classroom
from ...classroom.storage import SQLiteStore
from .models import ExplainRequest, ExplanationView, RecipientExplanation, StudentHistory
from .store import ExplanationStore


def explanations_router(classrooms: SQLiteStore) -> APIRouter:
    store = ExplanationStore(classrooms)
    router = APIRouter(prefix="/api", tags=["课堂角色报告"])

    @router.get("/classrooms/{cid}/care/students/{student_id}/history", response_model=StudentHistory)
    def history(cid: str, student_id: str, user: Annotated[User, Depends(require_teacher)]) -> StudentHistory:
        return store.history(cid, user.id, student_id)

    @router.post("/classrooms/{cid}/care/explanations", response_model=ExplanationView)
    def explain(cid: str, payload: ExplainRequest,
                user: Annotated[User, Depends(require_teacher)]) -> ExplanationView:
        return store.generate(cid, user.id, payload)

    @router.post("/care/me/explanations", response_model=RecipientExplanation)
    def recipient(payload: ExplainRequest, user: Annotated[User, Depends(current_user)]) -> RecipientExplanation:
        if user.role not in {"student", "parent"} or user.student_id != payload.comparison.student_id:
            raise HTTPException(403, "只能查看本人或已绑定孩子的解释")
        if payload.perspective != user.role:
            raise HTTPException(403, "接收者不能切换教师或其他角色视角")
        with classrooms.connection() as db:
            available = [Classroom.model_validate_json(row[0]) for row in
                         db.execute("SELECT payload FROM classrooms ORDER BY rowid DESC").fetchall()]
        classroom = next((item for item in available if user.student_id in item.students), None)
        if classroom is None:
            raise HTTPException(404, "没有可访问的课堂记录")
        record = store.generate(classroom.id, classroom.teacher_id, payload)
        return RecipientExplanation(id=record.id, student_id=record.student_id, perspective=user.role,
                                    source_fingerprint=record.source_fingerprint, model=record.model,
                                    content=record.content)

    return router
