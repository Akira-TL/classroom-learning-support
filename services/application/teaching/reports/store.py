"""发布和读取均在事务内检查依据；失效报告不再提供正文。"""

import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from ..classroom.auth import USERS, User
from ..classroom.storage import SQLiteStore, StoreError
from ..learning.store import EvidenceStore
from .models import (
    ParentQuestion,
    ParentReport,
    PreviewRequest,
    PublishRequest,
    QuestionRequest,
    ReportPreview,
    ReportView,
    ResolveQuestion,
    RevokeRequest,
)


class ReportStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self.evidence = EvidenceStore(store)
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS parent_reports (
                    id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    request TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(classroom_id, request_key)
                );
                CREATE TABLE IF NOT EXISTS parent_questions (
                    id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, report_id TEXT NOT NULL,
                    parent_id TEXT NOT NULL, request_key TEXT NOT NULL, request TEXT NOT NULL, body TEXT NOT NULL,
                    UNIQUE(report_id, parent_id, request_key)
                );
            """)

    def _preview(self, db: sqlite3.Connection, cid: str, teacher: str, content: PreviewRequest) -> ReportPreview:
        evidence = self.evidence.require_confirmed(
            db,
            cid,
            teacher,
            content.evidence_id,
            content.expected_evidence_revision,
        )
        if content.student_id != evidence.basis.context.student_alias:
            raise StoreError(422, "报告学生与证据所属学生不一致")
        parent = next((u for u in USERS if u.role == "parent" and u.student_id == content.student_id), None)
        if parent is None:
            raise StoreError(409, "该学生没有有效家长绑定")
        return ReportPreview(content=content, parent_id=parent.id)

    def preview(self, cid: str, teacher: str, content: PreviewRequest) -> ReportPreview:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._preview(db, cid, teacher, content)

    def publish(self, cid: str, teacher: str, request: PublishRequest) -> ReportView:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT request, body FROM parent_reports WHERE classroom_id=? AND request_key=?",
                (cid, request.idempotency_key),
            ).fetchone()
            if row:
                if PublishRequest.model_validate_json(row[0]) != request:
                    raise StoreError(409, "相同幂等标识不能用于不同发布内容")
                return self._view(db, ParentReport.model_validate_json(row[1]))
            content = PreviewRequest.model_validate(request.model_dump(exclude={"idempotency_key"}))
            preview = self._preview(db, cid, teacher, content)
            report = ParentReport(
                id=uuid4().hex,
                classroom_id=cid,
                parent_id=preview.parent_id,
                student_id=content.student_id,
                teacher_id=teacher,
                published_at=datetime.now(UTC),
                content=content,
            )
            db.execute(
                "INSERT INTO parent_reports VALUES (?, ?, ?, ?, ?)",
                (
                    report.id,
                    cid,
                    request.idempotency_key,
                    request.model_dump_json(),
                    report.model_dump_json(),
                ),
            )
            return self._view(db, report)

    def _record(self, db: sqlite3.Connection, report_id: str) -> ParentReport:
        row = db.execute("SELECT body FROM parent_reports WHERE id=?", (report_id,)).fetchone()
        if not row:
            raise StoreError(404, "报告不存在")
        return ParentReport.model_validate_json(row[0])

    def _view(self, db: sqlite3.Connection, report: ParentReport) -> ReportView:
        status = report.status
        if status == "published":
            try:
                self.evidence.require_confirmed(
                    db,
                    report.classroom_id,
                    report.teacher_id,
                    report.content.evidence_id,
                    report.content.expected_evidence_revision,
                )
            except StoreError as error:
                if error.status not in {404, 409}:
                    raise
                status = "stale"
        return ReportView(
            id=report.id,
            classroom_id=report.classroom_id,
            student_id=report.student_id,
            revision=report.revision,
            status=status,
            published_at=report.published_at,
            summary=report.content.summary if status == "published" else None,
            home_activity=report.content.home_activity if status == "published" else None,
            evidence_id=report.content.evidence_id,
            evidence_revision=report.content.expected_evidence_revision,
        )

    def _read(self, db: sqlite3.Connection, report_id: str, user: User) -> ReportView:
        report = self._record(db, report_id)
        if user.role == "teacher":
            self.store.get_classroom(user.id, report.classroom_id)
        elif user.role != "parent" or user.id != report.parent_id or user.student_id != report.student_id:
            raise StoreError(403, "无权访问该家长报告")
        view = self._view(db, report)
        if user.role == "parent" and view.status != "published":
            raise StoreError(410, "报告已撤回或依据已变化，请等待教师发布新版")
        return view

    def read(self, report_id: str, user: User) -> ReportView:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._read(db, report_id, user)

    def list_reports(self, cid: str, teacher: str) -> list[ReportView]:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT body FROM parent_reports WHERE classroom_id=? ORDER BY rowid", (cid,)).fetchall()
            return [self._view(db, ParentReport.model_validate_json(row[0])) for row in rows]

    def parent_reports(self, user: User) -> list[ReportView]:
        if user.role != "parent":
            raise StoreError(403, "此操作需要家长权限")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT body FROM parent_reports ORDER BY rowid DESC").fetchall()
            reports = [ParentReport.model_validate_json(row[0]) for row in rows]
            return [
                self._view(db, report)
                for report in reports
                if report.parent_id == user.id and report.student_id == user.student_id
            ]

    def parent_questions(self, report_id: str, user: User) -> list[ParentQuestion]:
        with self.store.connection() as db:
            report = self._record(db, report_id)
            if user.role != "parent" or report.parent_id != user.id or report.student_id != user.student_id:
                raise StoreError(403, "无权查看此报告的家长疑问")
            rows = db.execute(
                "SELECT body FROM parent_questions WHERE report_id=? AND parent_id=? ORDER BY rowid",
                (report_id, user.id),
            ).fetchall()
            return [ParentQuestion.model_validate_json(row[0]) for row in rows]

    def revoke(self, cid: str, report_id: str, teacher: str, request: RevokeRequest) -> ReportView:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            report = self._record(db, report_id)
            if report.classroom_id != cid:
                raise StoreError(404, "报告不属于该课堂")
            if report.revision != request.expected_revision:
                raise StoreError(409, "报告版本已变化")
            if report.status != "revoked":
                report = report.model_copy(update={"revision": report.revision + 1, "status": "revoked"})
                db.execute("UPDATE parent_reports SET body=? WHERE id=?", (report.model_dump_json(), report.id))
            return self._view(db, report)

    def ask(self, report_id: str, user: User, request: QuestionRequest) -> ParentQuestion:
        if user.role != "parent":
            raise StoreError(403, "此操作需要家长权限")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            view = self._read(db, report_id, user)
            row = db.execute(
                "SELECT request, body FROM parent_questions WHERE report_id=? AND parent_id=? AND request_key=?",
                (report_id, user.id, request.idempotency_key),
            ).fetchone()
            if row:
                if QuestionRequest.model_validate_json(row[0]) != request:
                    raise StoreError(409, "相同幂等标识不能用于不同疑问")
                return ParentQuestion.model_validate_json(row[1])
            question = ParentQuestion(
                id=uuid4().hex,
                report_id=report_id,
                classroom_id=view.classroom_id,
                parent_id=user.id,
                text=request.text,
            )
            db.execute(
                "INSERT INTO parent_questions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    question.id,
                    view.classroom_id,
                    report_id,
                    user.id,
                    request.idempotency_key,
                    request.model_dump_json(),
                    question.model_dump_json(),
                ),
            )
            return question

    def questions(self, cid: str, teacher: str) -> list[ParentQuestion]:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            rows = db.execute(
                "SELECT body FROM parent_questions WHERE classroom_id=? ORDER BY rowid", (cid,)
            ).fetchall()
        return [ParentQuestion.model_validate_json(row[0]) for row in rows]

    def resolve(self, cid: str, teacher: str, question_id: str, request: ResolveQuestion) -> ParentQuestion:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM parent_questions WHERE id=? AND classroom_id=?",
                (question_id, cid),
            ).fetchone()
            if not row:
                raise StoreError(404, "疑问不存在")
            question = ParentQuestion.model_validate_json(row[0])
            if request.expected_revision != question.revision:
                raise StoreError(409, "疑问处理版本已变化")
            question = question.model_copy(
                update={
                    "revision": question.revision + 1,
                    "status": request.status,
                    "response": request.response,
                }
            )
            db.execute("UPDATE parent_questions SET body=? WHERE id=?", (question.model_dump_json(), question_id))
            return question
