from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..classroom.auth import User, current_user, require_teacher
from ..classroom.storage import SQLiteStore
from .compare import compare
from .models import (
    CareReport,
    CompareRequest,
    Comparison,
    Observation,
    ObservationInput,
    ObservationUpdate,
    RecipientReport,
    ReportAction,
    ReportInput,
)
from .reports import act, create_report, refreshed
from .store import CareStore


def care_router(classrooms: SQLiteStore) -> APIRouter:
    store = CareStore(classrooms)
    router = APIRouter(prefix="/api", tags=["学生关怀"])

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

    @router.post("/classrooms/{cid}/care/reports", response_model=CareReport)
    def draft(cid: str, payload: ReportInput, user: Annotated[User, Depends(require_teacher)]) -> CareReport:
        return create_report(store, cid, user.id, payload)

    @router.get("/classrooms/{cid}/care/reports", response_model=list[CareReport])
    def reports(cid: str, user: Annotated[User, Depends(require_teacher)]) -> list[CareReport]:
        with classrooms.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            classrooms._authorized(db, user.id, cid)
            rows = db.execute("SELECT body FROM care_reports WHERE classroom_id=? AND teacher_id=?",
                              (cid, user.id)).fetchall()
            return [refreshed(db, store, CareReport.model_validate_json(row[0])) for row in rows]

    @router.post("/classrooms/{cid}/care/reports/{rid}/action", response_model=CareReport)
    def action(cid: str, rid: str, payload: ReportAction,
               user: Annotated[User, Depends(require_teacher)]) -> CareReport:
        return act(store, cid, user.id, rid, payload)

    @router.get("/care/me", response_model=list[RecipientReport])
    def mine(user: Annotated[User, Depends(current_user)]) -> list[RecipientReport]:
        if user.role not in {"student", "parent"} or not user.student_id:
            raise HTTPException(403, "此入口仅向学生本人或绑定家长提供已发布文字")
        with classrooms.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT r.body FROM care_reports r JOIN classrooms c ON c.id=r.classroom_id").fetchall()
            result: list[RecipientReport] = []
            for row in rows:
                report = CareReport.model_validate_json(row[0])
                if report.student_id != user.student_id:
                    continue
                report = refreshed(db, store, report)
                if report.status == "published":
                    result.append(RecipientReport(id=report.id, revision=report.revision,
                                                  student_id=report.student_id, audience=user.role,
                                                  text=report.student_text if user.role == "student"
                                                  else report.parent_text))
            return result

    return router
