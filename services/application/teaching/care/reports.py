import sqlite3
from uuid import uuid4

from ..classroom.storage import StoreError
from .compare import compare
from .models import CareReport, ReportAction, ReportInput
from .store import CareStore


def basis_current(db: sqlite3.Connection, store: CareStore, report: ReportInput, teacher: str) -> bool:
    result = compare(db, store, teacher, report.comparison)
    actual = {(item.id, item.revision) for item in result.baseline + result.current}
    expected = {(item.observation_id, item.revision) for item in report.basis}
    return bool(actual) and actual == expected and len(expected) == len(report.basis)


def refreshed(db: sqlite3.Connection, store: CareStore, report: CareReport) -> CareReport:
    if report.status in {"draft", "published"} and not basis_current(db, store, report, report.teacher_id):
        report = report.model_copy(update={"status": "stale", "revision": report.revision + 1})
        store.write_report(db, report)
    return report


def create_report(store: CareStore, cid: str, teacher: str, payload: ReportInput) -> CareReport:
    with store.store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        classroom = store.store._authorized(db, teacher, cid)
        if payload.comparison.student_id not in classroom.students:
            raise StoreError(422, "学生不属于当前课堂")
        if not basis_current(db, store, payload, teacher):
            raise StoreError(409, "比较依据已变化或未完整选择已核验观察，请重新比较")
        report = CareReport(**payload.model_dump(), id=uuid4().hex, classroom_id=cid, teacher_id=teacher,
                            student_id=payload.comparison.student_id)
        store.write_report(db, report)
        return report


def act(store: CareStore, cid: str, teacher: str, rid: str, request: ReportAction) -> CareReport:
    with store.store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        store.store._authorized(db, teacher, cid)
        report = store.report(db, cid, teacher, rid)
        if report.revision != request.expected_revision:
            raise StoreError(409, "关怀记录版本已变化，请刷新")
        if request.action == "publish":
            if report.status != "draft" or not basis_current(db, store, report, teacher):
                raise StoreError(409, "只有来源仍有效的关怀草稿可由教师确认发布")
            status = "published"
        else:
            if report.status != "published":
                raise StoreError(409, "只有已发布记录可以撤回")
            status = "revoked"
        report = report.model_copy(update={"status": status, "revision": report.revision + 1})
        store.write_report(db, report)
        return report
