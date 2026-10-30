"""生成调用期间不持锁；结果写入前在事务中重新核对语义依据。"""

import sqlite3
from uuid import uuid4

import httpx

from ..classroom.storage import SQLiteStore, StoreError
from ..deepseek import DeepSeek, GenerationError
from ..models import EvidenceDraft
from .context import build_basis
from .manual import save_manual
from .models import (
    EvidenceRecord,
    EvidenceReview,
    EvidenceTask,
    GenerateEvidence,
    GenerationResult,
    ManualEvidenceRequest,
)


class EvidenceStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS evidence_tasks (
                    id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    body TEXT NOT NULL, UNIQUE(classroom_id, request_key)
                );
                CREATE TABLE IF NOT EXISTS evidence_records (
                    id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, task_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence_reviews (
                    evidence_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(evidence_id, revision)
                );
            """)

    def require_confirmed(
        self,
        db: sqlite3.Connection,
        cid: str,
        teacher: str,
        evidence_id: str,
        revision: int,
    ) -> EvidenceRecord:
        """在调用方的发布或采用事务内检查当前证据，不信任先前读出的状态。"""
        owner = db.execute("SELECT teacher_id FROM classrooms WHERE id=?", (cid,)).fetchone()
        if not owner:
            raise StoreError(404, "课堂不存在")
        if owner[0] != teacher:
            raise StoreError(403, "无权访问该课堂")
        row = db.execute(
            "SELECT body FROM evidence_records WHERE id=? AND classroom_id=?", (evidence_id, cid)
        ).fetchone()
        if not row:
            raise StoreError(404, "证据不存在")
        record = EvidenceRecord.model_validate_json(row[0])
        task_row = db.execute("SELECT body FROM evidence_tasks WHERE id=?", (record.task_id,)).fetchone()
        if not task_row:
            raise StoreError(409, "证据来源任务缺失，不能采用或发布")
        current = self._refresh(db, EvidenceTask.model_validate_json(task_row[0]), teacher).evidence
        if current is None or current.status != "confirmed" or current.revision != revision:
            raise StoreError(409, "需要当前版本的已确认证据，请重新核验")
        return current

    def _is_current(self, db: sqlite3.Connection, task: EvidenceTask, teacher: str) -> bool:
        try:
            return build_basis(db, task.classroom_id, teacher, task.request) == task.basis
        except StoreError:
            return False

    def _record(self, db: sqlite3.Connection, task_id: str) -> EvidenceRecord | None:
        row = db.execute("SELECT body FROM evidence_records WHERE task_id=?", (task_id,)).fetchone()
        return EvidenceRecord.model_validate_json(row[0]) if row else None

    def _save_task(self, db: sqlite3.Connection, task: EvidenceTask) -> None:
        db.execute("UPDATE evidence_tasks SET body=? WHERE id=?", (task.model_dump_json(), task.id))

    def _save_record(self, db: sqlite3.Connection, record: EvidenceRecord) -> None:
        db.execute("UPDATE evidence_records SET body=? WHERE id=?", (record.model_dump_json(), record.id))

    def _refresh(self, db: sqlite3.Connection, task: EvidenceTask, teacher: str) -> GenerationResult:
        record = self._record(db, task.id)
        if not self._is_current(db, task, teacher):
            task = task.model_copy(update={"status": "stale", "error": "依据已变化，需重新核验和生成"})
            self._save_task(db, task)
            if record and record.status != "stale":
                record = record.model_copy(update={"status": "stale", "revision": record.revision + 1})
                self._save_record(db, record)
        return GenerationResult(task=task, evidence=record)

    def manual(self, cid: str, teacher: str, request: ManualEvidenceRequest) -> GenerationResult:
        return save_manual(self, cid, teacher, request)

    def generate(self, cid: str, teacher: str, request: GenerateEvidence) -> GenerationResult:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM evidence_tasks WHERE classroom_id=? AND request_key=?",
                (cid, request.idempotency_key),
            ).fetchone()
            if row:
                task = EvidenceTask.model_validate_json(row[0])
                if task.origin != "deepseek" or task.request != request:
                    raise StoreError(409, "相同幂等标识不能用于不同生成请求")
                return self._refresh(db, task, teacher)
            basis = build_basis(db, cid, teacher, request)
            if basis.utterance_version != request.expected_version:
                raise StoreError(409, "发言版本已变化，请重新读取")
            task = EvidenceTask(id=uuid4().hex, classroom_id=cid, request=request, basis=basis, status="running")
            db.execute(
                "INSERT INTO evidence_tasks VALUES (?, ?, ?, ?)",
                (task.id, cid, request.idempotency_key, task.model_dump_json()),
            )
        draft: EvidenceDraft | None = None
        failure: str | None = None
        try:
            with httpx.Client(trust_env=False) as client:
                draft = DeepSeek.from_environment(client).analyze(task.basis.context)
        except GenerationError as error:
            failure = str(error)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM classrooms WHERE id=?", (cid,)).fetchone():
                raise StoreError(410, "课堂已删除，迟到生成结果已丢弃")
            if not self._is_current(db, task, teacher):
                task = task.model_copy(
                    update={
                        "status": "stale",
                        "error": "生成期间依据变化，结果未采用",
                        "discarded_draft": draft,
                    }
                )
            elif failure:
                task = task.model_copy(update={"status": "failed", "error": failure})
            elif draft:
                task = task.model_copy(update={"status": "succeeded"})
                record = EvidenceRecord(
                    id=uuid4().hex,
                    task_id=task.id,
                    classroom_id=cid,
                    basis=task.basis,
                    original=draft,
                    content=draft.content,
                )
                db.execute(
                    "INSERT INTO evidence_records VALUES (?, ?, ?, ?)",
                    (record.id, cid, task.id, record.model_dump_json()),
                )
            self._save_task(db, task)
            return GenerationResult(task=task, evidence=self._record(db, task.id))

    def list(self, cid: str, teacher: str) -> list[GenerationResult]:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT body FROM evidence_tasks WHERE classroom_id=? ORDER BY rowid", (cid,)).fetchall()
            return [self._refresh(db, EvidenceTask.model_validate_json(row[0]), teacher) for row in rows]

    def review(self, cid: str, teacher: str, evidence_id: str, request: EvidenceReview) -> EvidenceRecord:
        self.store.get_classroom(teacher, cid)
        failure: StoreError | None = None
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM evidence_records WHERE id=? AND classroom_id=?",
                (evidence_id, cid),
            ).fetchone()
            if not row:
                raise StoreError(404, "证据不存在")
            record = EvidenceRecord.model_validate_json(row[0])
            task_row = db.execute("SELECT body FROM evidence_tasks WHERE id=?", (record.task_id,)).fetchone()
            result = self._refresh(db, EvidenceTask.model_validate_json(task_row[0]), teacher)
            record = result.evidence
            if record.status == "stale":
                failure = StoreError(409, "证据依据已变化，需重新核验和生成")
            elif record.revision != request.expected_revision:
                failure = StoreError(409, "证据版本已变化，请重新读取")
            elif request.content and request.content.quote != record.basis.context.utterance:
                failure = StoreError(422, "证据引用必须与核验原话一致")
            else:
                record = record.model_copy(
                    update={
                        "content": request.content or record.content,
                        "revision": record.revision + 1,
                        "status": request.action,
                        "reviewed_by": teacher,
                    }
                )
                self._save_record(db, record)
                db.execute(
                    "INSERT INTO evidence_reviews VALUES (?, ?, ?)",
                    (record.id, record.revision, record.model_dump_json()),
                )
        if failure:
            raise failure
        return record
