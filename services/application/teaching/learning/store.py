"""生成调用期间不持锁；结果写入前在事务中重新核对语义依据。"""

import hashlib
import sqlite3
from uuid import uuid4

import httpx
from pydantic import ValidationError

from ..audio.models import Utterance
from ..classroom.classrooms import Classroom
from ..classroom.storage import SQLiteStore, StoreError
from ..deepseek import DeepSeek, GenerationError
from ..models import EvidenceDraft, VerifiedContext
from .models import (
    EvidenceBasis,
    EvidenceRecord,
    EvidenceReview,
    EvidenceTask,
    GenerateEvidence,
    GenerationResult,
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

    def _basis(self, db: sqlite3.Connection, cid: str, teacher: str, request: GenerateEvidence) -> EvidenceBasis:
        row = db.execute("SELECT payload FROM classrooms WHERE id=?", (cid,)).fetchone()
        if not row:
            raise StoreError(404, "课堂不存在")
        classroom = Classroom.model_validate_json(row[0])
        if classroom.teacher_id != teacher:
            raise StoreError(403, "无权访问课堂")
        row = db.execute(
            "SELECT body FROM utterances WHERE classroom_id=? AND session_id=? AND segment_id=?",
            (cid, request.session_id, request.segment_id),
        ).fetchone()
        if not row:
            raise StoreError(404, "发言不存在")
        utterance = Utterance.model_validate_json(row[0])
        if utterance.phase not in {"final", "revision"} or (
            utterance.text_review,
            utterance.identity_review,
            utterance.question_review,
        ) != ("confirmed", "confirmed", "confirmed"):
            raise StoreError(409, "发言文字、身份和题目须分别核验")
        if utterance.student_alias not in classroom.students:
            raise StoreError(409, "发言学生不在当前课堂名单")
        question = next((item for item in classroom.questions if item.id == utterance.question_id), None)
        if question is None:
            raise StoreError(409, "发言题目不属于当前课堂")
        fingerprint = hashlib.sha256(question.model_dump_json().encode()).hexdigest()
        try:
            context = VerifiedContext(
                question_id=question.id,
                question_revision=int(fingerprint[:12], 16) + 1,
                objective=classroom.objective,
                question=question.text,
                reference_answer=question.reference_answer,
                diagram_required=question.diagram_required,
                diagram_description=question.diagram_description,
                utterance_id=utterance.segment_id,
                utterance_revision=utterance.version,
                student_alias=utterance.student_alias,
                utterance=utterance.teacher_text or utterance.upstream_text,
                text_confirmed=True,
                identity_confirmed=True,
                question_confirmed=True,
            )
        except ValidationError:
            raise StoreError(422, "教学上下文不足，请补充题目图形等必要内容") from None
        return EvidenceBasis(
            session_id=request.session_id,
            segment_id=request.segment_id,
            utterance_version=utterance.version,
            question_fingerprint=fingerprint,
            context=context,
        )

    def _is_current(self, db: sqlite3.Connection, task: EvidenceTask, teacher: str) -> bool:
        try:
            return self._basis(db, task.classroom_id, teacher, task.request) == task.basis
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
                if task.request != request:
                    raise StoreError(409, "相同幂等标识不能用于不同生成请求")
                return self._refresh(db, task, teacher)
            basis = self._basis(db, cid, teacher, request)
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
