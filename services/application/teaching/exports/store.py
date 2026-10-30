import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from ..classroom.classrooms import Classroom
from ..classroom.storage import SQLiteStore, StoreError
from ..learning.store import EvidenceStore
from ..plans.models import PlanRecord
from ..reports.models import ParentReport
from .models import CreateExport, ExportMetadata, ExportRecord, ExportSources, RevokeExport
from .render import render_report


class ExportStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self.evidence = EvidenceStore(store)
        self.directory = store.path.parent / "exports"
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS teacher_exports (
                    id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, teacher_id TEXT NOT NULL,
                    request_key TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(classroom_id,request_key)
                );
                CREATE TABLE IF NOT EXISTS export_status (
                    id TEXT PRIMARY KEY, revision INTEGER NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL
                );
            """)

    def _sources(self, db: sqlite3.Connection, cid: str, teacher: str, request: CreateExport) -> ExportSources:
        row = db.execute("SELECT payload FROM classrooms WHERE id=?", (cid,)).fetchone()
        if not row:
            raise StoreError(404, "课堂不存在")
        classroom = Classroom.model_validate_json(row[0])
        if classroom.teacher_id != teacher:
            raise StoreError(403, "无权导出此课堂")
        row = db.execute(
            "SELECT body FROM plan_records WHERE id=? AND classroom_id=?", (request.plan_id, cid)
        ).fetchone()
        if not row:
            raise StoreError(404, "教学安排不存在")
        plan = PlanRecord.model_validate_json(row[0])
        if plan.status != "confirmed" or plan.revision != request.expected_plan_revision or not plan.content.complete():
            raise StoreError(409, "教学安排须为当前完整的教师确认版本")
        evidence = self.evidence.require_confirmed(db, cid, teacher, plan.evidence_id, plan.evidence_revision)
        if plan.content.target_student != evidence.basis.context.student_alias:
            raise StoreError(409, "教学安排对象与证据不一致")
        parent: ParentReport | None = None
        if request.parent_report_id:
            row = db.execute(
                "SELECT body FROM parent_reports WHERE id=? AND classroom_id=?", (request.parent_report_id, cid)
            ).fetchone()
            if not row:
                raise StoreError(404, "家长报告不存在")
            parent = ParentReport.model_validate_json(row[0])
            if (
                parent.status != "published"
                or parent.revision != request.expected_parent_revision
                or parent.teacher_id != teacher
                or parent.student_id != plan.content.target_student
            ):
                raise StoreError(409, "家长报告版本、状态或所属学生不一致")
            self.evidence.require_confirmed(
                db, cid, teacher, parent.content.evidence_id, parent.content.expected_evidence_revision
            )
        return ExportSources(classroom=classroom, evidence=evidence, plan=plan, parent=parent)

    def _metadata(self, db: sqlite3.Connection, export_id: str) -> ExportMetadata:
        row = db.execute("SELECT revision,created_at,status FROM export_status WHERE id=?", (export_id,)).fetchone()
        if not row:
            raise StoreError(404, "导出记录不存在")
        return ExportMetadata(id=export_id, revision=row[0], created_at=datetime.fromisoformat(row[1]), status=row[2])

    def _record(self, db: sqlite3.Connection, export_id: str) -> ExportRecord | None:
        row = db.execute("SELECT body FROM teacher_exports WHERE id=?", (export_id,)).fetchone()
        return ExportRecord.model_validate_json(row[0]) if row else None

    def _refresh(self, db: sqlite3.Connection, metadata: ExportMetadata) -> ExportMetadata:
        if metadata.status != "active":
            return metadata
        record = self._record(db, metadata.id)
        state: str | None = None
        if not record:
            state = "deleted"
        elif not (self.directory / f"{metadata.id}.html").is_file():
            state = "deleted"
        else:
            try:
                self._sources(db, record.classroom_id, record.teacher_id, record.request)
            except StoreError:
                state = "stale"
        if state:
            db.execute("UPDATE export_status SET revision=revision+1,status=? WHERE id=?", (state, metadata.id))
            return self._metadata(db, metadata.id)
        return metadata

    def create(self, cid: str, teacher: str, request: CreateExport) -> ExportMetadata:
        self.store.get_classroom(teacher, cid)
        export_id = uuid4().hex
        temporary = self.directory / f"{export_id}.part"
        destination = self.directory / f"{export_id}.html"
        try:
            with self.store.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT body FROM teacher_exports WHERE classroom_id=? AND request_key=?",
                    (cid, request.idempotency_key),
                ).fetchone()
                if row:
                    record = ExportRecord.model_validate_json(row[0])
                    if record.request != request:
                        raise StoreError(409, "相同幂等标识不能用于不同导出请求")
                    return self._refresh(db, self._metadata(db, record.id))
                source = self._sources(db, cid, teacher, request)
                metadata = ExportMetadata(id=export_id, revision=1, created_at=datetime.now(UTC), status="active")
                self.directory.mkdir(exist_ok=True)
                temporary.write_text(render_report(metadata, source), encoding="utf-8")
                self._sources(db, cid, teacher, request)
                temporary.replace(destination)
                record = ExportRecord(id=export_id, classroom_id=cid, teacher_id=teacher, request=request)
                db.execute(
                    "INSERT INTO teacher_exports VALUES (?, ?, ?, ?, ?)",
                    (export_id, cid, teacher, request.idempotency_key, record.model_dump_json()),
                )
                db.execute(
                    "INSERT INTO export_status VALUES (?, ?, ?, ?)",
                    (export_id, 1, metadata.created_at.isoformat(), "active"),
                )
            return metadata
        except BaseException:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise

    def list(self, cid: str, teacher: str) -> list[ExportMetadata]:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id FROM teacher_exports WHERE classroom_id=? ORDER BY rowid", (cid,)).fetchall()
            return [self._refresh(db, self._metadata(db, row[0])) for row in rows]

    def status(self, export_id: str) -> ExportMetadata:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._refresh(db, self._metadata(db, export_id))

    def download(self, export_id: str, teacher: str) -> str:
        failure: StoreError | None = None
        content: str | None = None
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self._record(db, export_id)
            if not record:
                if self._metadata(db, export_id).status == "deleted":
                    raise StoreError(410, "导出报告已删除")
                raise StoreError(404, "导出记录不存在")
            if record.teacher_id != teacher:
                raise StoreError(403, "无权下载该报告")
            metadata = self._refresh(db, self._metadata(db, export_id))
            if metadata.status != "active":
                failure = StoreError(410, "导出报告已撤回、删除或失效")
            else:
                try:
                    content = (self.directory / f"{export_id}.html").read_text(encoding="utf-8")
                except OSError:
                    failure = StoreError(410, "导出文件不可用，请重新导出")
        if failure:
            raise failure
        return content

    def revoke(self, cid: str, teacher: str, export_id: str, request: RevokeExport) -> ExportMetadata:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self._record(db, export_id)
            if not record or record.classroom_id != cid:
                raise StoreError(404, "导出记录不存在")
            metadata = self._metadata(db, export_id)
            if metadata.revision != request.expected_revision:
                raise StoreError(409, "导出版本已变化")
            db.execute("UPDATE export_status SET revision=revision+1,status='revoked' WHERE id=?", (export_id,))
            return self._metadata(db, export_id)
