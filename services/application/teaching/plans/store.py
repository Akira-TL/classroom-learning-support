"""计划作为独立版本记录，生成与人工补全分别追踪。"""

import sqlite3
from uuid import uuid4

import httpx

from ..classroom.storage import SQLiteStore, StoreError
from ..deepseek import DeepSeek, GenerationError
from ..learning.store import EvidenceStore
from ..models import ConfirmedEvidence, SupportDraft
from .models import (
    GeneratePlan,
    Observation,
    PlanAdoption,
    PlanContent,
    PlanGenerationResult,
    PlanRecord,
    PlanReview,
    PlanTask,
)


class PlanStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self.evidence = EvidenceStore(store)
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS plan_tasks (
                    id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    body TEXT NOT NULL, UNIQUE(classroom_id, request_key)
                );
                CREATE TABLE IF NOT EXISTS plan_records (
                    id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, task_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plan_reviews (
                    record_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(record_id, revision)
                );
            """)

    def _record(self, db: sqlite3.Connection, task_id: str) -> PlanRecord | None:
        row = db.execute("SELECT body FROM plan_records WHERE task_id=?", (task_id,)).fetchone()
        return PlanRecord.model_validate_json(row[0]) if row else None

    def _current(self, db: sqlite3.Connection, task: PlanTask, teacher: str) -> bool:
        try:
            return (
                self.evidence.require_confirmed(
                    db,
                    task.classroom_id,
                    teacher,
                    task.request.evidence_id,
                    task.request.expected_evidence_revision,
                )
                == task.basis
            )
        except StoreError:
            return False

    def _save_task(self, db: sqlite3.Connection, task: PlanTask) -> None:
        db.execute("UPDATE plan_tasks SET body=? WHERE id=?", (task.model_dump_json(), task.id))

    def _save_record(self, db: sqlite3.Connection, record: PlanRecord) -> None:
        db.execute("UPDATE plan_records SET body=? WHERE id=?", (record.model_dump_json(), record.id))

    def _refresh(self, db: sqlite3.Connection, task: PlanTask, teacher: str) -> PlanGenerationResult:
        record = self._record(db, task.id)
        if not self._current(db, task, teacher):
            task = task.model_copy(update={"status": "stale", "error": "学习证据已变化，教学安排需重新核验"})
            self._save_task(db, task)
            if record and record.status != "stale":
                record = record.model_copy(
                    update={
                        "status": "stale",
                        "revision": record.revision + 1,
                        "adopted": False,
                        "adopted_by": None,
                    }
                )
                self._save_record(db, record)
        return PlanGenerationResult(task=task, plan=record)

    def generate(self, cid: str, teacher: str, request: GeneratePlan) -> PlanGenerationResult:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM plan_tasks WHERE classroom_id=? AND request_key=?", (cid, request.idempotency_key)
            ).fetchone()
            if row:
                task = PlanTask.model_validate_json(row[0])
                if task.request != request:
                    raise StoreError(409, "相同幂等标识不能用于不同计划请求")
                return self._refresh(db, task, teacher)
            basis = self.evidence.require_confirmed(
                db, cid, teacher, request.evidence_id, request.expected_evidence_revision
            )
            task = PlanTask(id=uuid4().hex, classroom_id=cid, request=request, basis=basis, status="running")
            db.execute(
                "INSERT INTO plan_tasks VALUES (?, ?, ?, ?)",
                (task.id, cid, request.idempotency_key, task.model_dump_json()),
            )
        draft: SupportDraft | None = None
        failure: str | None = None
        confirmed = ConfirmedEvidence(
            draft=task.basis.original.model_copy(update={"content": task.basis.content}),
            teacher_confirmed=True,
        )
        try:
            with httpx.Client(trust_env=False) as client:
                draft = DeepSeek.from_environment(client).support(confirmed)
        except GenerationError as error:
            failure = str(error)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM classrooms WHERE id=?", (cid,)).fetchone():
                raise StoreError(410, "课堂已删除，迟到生成结果已丢弃")
            if not self._current(db, task, teacher):
                task = task.model_copy(
                    update={
                        "status": "stale",
                        "error": "生成期间依据变化，教学安排未采用",
                        "discarded_draft": draft,
                    }
                )
            elif failure:
                task = task.model_copy(update={"status": "failed", "error": failure})
            elif draft:
                task = task.model_copy(update={"status": "succeeded"})
                record = PlanRecord(
                    id=uuid4().hex,
                    task_id=task.id,
                    classroom_id=cid,
                    evidence_id=task.basis.id,
                    evidence_revision=task.basis.revision,
                    original=draft,
                    content=PlanContent(
                        target_student=task.basis.basis.context.student_alias,
                        question=draft.content.classroom_question,
                        activity=draft.content.next_lesson,
                        check_method=draft.content.check_method,
                    ),
                )
                db.execute(
                    "INSERT INTO plan_records VALUES (?, ?, ?, ?)", (record.id, cid, task.id, record.model_dump_json())
                )
            self._save_task(db, task)
            return PlanGenerationResult(task=task, plan=self._record(db, task.id))

    def list(self, cid: str, teacher: str) -> list[PlanGenerationResult]:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT body FROM plan_tasks WHERE classroom_id=? ORDER BY rowid", (cid,)).fetchall()
            return [self._refresh(db, PlanTask.model_validate_json(row[0]), teacher) for row in rows]

    def update(self, cid: str, teacher: str, record_id: str, request: PlanReview | PlanAdoption) -> PlanRecord:
        self.store.get_classroom(teacher, cid)
        failure: StoreError | None = None
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM plan_records WHERE id=? AND classroom_id=?", (record_id, cid)).fetchone()
            if not row:
                raise StoreError(404, "教学安排不存在")
            record = PlanRecord.model_validate_json(row[0])
            row = db.execute("SELECT body FROM plan_tasks WHERE id=?", (record.task_id,)).fetchone()
            record = self._refresh(db, PlanTask.model_validate_json(row[0]), teacher).plan
            content = request.content or record.content if isinstance(request, PlanReview) else record.content
            if record.status == "stale":
                failure = StoreError(409, "教学安排依据已过期")
            elif record.revision != request.expected_revision:
                failure = StoreError(409, "教学安排版本已变化，请重新读取")
            elif content.target_student != record.original.evidence.draft.context.student_alias:
                failure = StoreError(422, "个人安排的对象须与已确认证据一致")
            elif isinstance(request, PlanReview) and request.action == "confirmed" and not content.complete():
                failure = StoreError(422, "需由教师补充准备方式、备选安排和下一课保留内容")
            elif (
                isinstance(request, PlanAdoption)
                and request.adopted
                and (record.status != "confirmed" or not content.complete())
            ):
                failure = StoreError(409, "只有完整并经教师确认的教学安排才能采用")
            else:
                if isinstance(request, PlanReview):
                    record = record.model_copy(
                        update={
                            "content": content,
                            "status": request.action,
                            "reviewed_by": teacher,
                            "adopted": False,
                            "adopted_by": None,
                        }
                    )
                else:
                    observations = record.observations
                    if request.observation:
                        observations = [
                            *observations,
                            Observation(text=request.observation, teacher=teacher, revision=record.revision + 1),
                        ]
                    record = record.model_copy(
                        update={
                            "adopted": request.adopted,
                            "adopted_by": teacher if request.adopted else None,
                            "observations": observations,
                        }
                    )
                record = record.model_copy(update={"revision": record.revision + 1})
                self._save_record(db, record)
                db.execute(
                    "INSERT INTO plan_reviews VALUES (?, ?, ?)", (record.id, record.revision, record.model_dump_json())
                )
        if failure:
            raise failure
        return record
