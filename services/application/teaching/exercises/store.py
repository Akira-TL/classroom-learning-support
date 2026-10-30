"""练习生成、核验与采用；全部状态以有效证据版本为前提。"""

import sqlite3
from uuid import uuid4

import httpx

from ..classroom.storage import SQLiteStore, StoreError
from ..deepseek import DeepSeek, GenerationError
from ..learning.store import EvidenceStore
from ..models import ConfirmedEvidence, SupportDraft
from .models import (
    ExerciseAdoption,
    ExerciseGenerationResult,
    ExerciseRecord,
    ExerciseReview,
    ExerciseTask,
    GenerateExercises,
)


class ExerciseStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self.evidence = EvidenceStore(store)
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS exercise_tasks (
                    id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    body TEXT NOT NULL, UNIQUE(classroom_id, request_key)
                );
                CREATE TABLE IF NOT EXISTS exercise_sets (
                    id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, task_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS exercise_reviews (
                    record_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(record_id, revision)
                );
            """)

    def _record(self, db: sqlite3.Connection, task_id: str) -> ExerciseRecord | None:
        row = db.execute("SELECT body FROM exercise_sets WHERE task_id=?", (task_id,)).fetchone()
        return ExerciseRecord.model_validate_json(row[0]) if row else None

    def _current(self, db: sqlite3.Connection, task: ExerciseTask, teacher: str) -> bool:
        try:
            current = self.evidence.require_confirmed(
                db,
                task.classroom_id,
                teacher,
                task.request.evidence_id,
                task.request.expected_evidence_revision,
            )
            return current == task.basis
        except StoreError:
            return False

    def _save_task(self, db: sqlite3.Connection, task: ExerciseTask) -> None:
        db.execute("UPDATE exercise_tasks SET body=? WHERE id=?", (task.model_dump_json(), task.id))

    def _save_record(self, db: sqlite3.Connection, record: ExerciseRecord) -> None:
        db.execute("UPDATE exercise_sets SET body=? WHERE id=?", (record.model_dump_json(), record.id))

    def _refresh(self, db: sqlite3.Connection, task: ExerciseTask, teacher: str) -> ExerciseGenerationResult:
        record = self._record(db, task.id)
        if not self._current(db, task, teacher):
            task = task.model_copy(update={"status": "stale", "error": "学习证据已变化，练习需重新核验"})
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
        return ExerciseGenerationResult(task=task, exercise_set=record)

    def generate(self, cid: str, teacher: str, request: GenerateExercises) -> ExerciseGenerationResult:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM exercise_tasks WHERE classroom_id=? AND request_key=?",
                (cid, request.idempotency_key),
            ).fetchone()
            if row:
                task = ExerciseTask.model_validate_json(row[0])
                if task.request != request:
                    raise StoreError(409, "相同幂等标识不能用于不同练习请求")
                return self._refresh(db, task, teacher)
            basis = self.evidence.require_confirmed(
                db,
                cid,
                teacher,
                request.evidence_id,
                request.expected_evidence_revision,
            )
            task = ExerciseTask(id=uuid4().hex, classroom_id=cid, request=request, basis=basis, status="running")
            db.execute(
                "INSERT INTO exercise_tasks VALUES (?, ?, ?, ?)",
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
            if not self._current(db, task, teacher):
                task = task.model_copy(
                    update={
                        "status": "stale",
                        "error": "生成期间学习证据变化，练习未采用",
                        "discarded_draft": draft,
                    }
                )
            elif failure:
                task = task.model_copy(update={"status": "failed", "error": failure})
            elif draft:
                task = task.model_copy(update={"status": "succeeded"})
                record = ExerciseRecord(
                    id=uuid4().hex,
                    task_id=task.id,
                    classroom_id=cid,
                    evidence_id=task.basis.id,
                    evidence_revision=task.basis.revision,
                    original=draft,
                    exercises=draft.content.exercises,
                )
                db.execute(
                    "INSERT INTO exercise_sets VALUES (?, ?, ?, ?)", (record.id, cid, task.id, record.model_dump_json())
                )
            self._save_task(db, task)
            return ExerciseGenerationResult(task=task, exercise_set=self._record(db, task.id))

    def list(self, cid: str, teacher: str) -> list[ExerciseGenerationResult]:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT body FROM exercise_tasks WHERE classroom_id=? ORDER BY rowid", (cid,)).fetchall()
            return [self._refresh(db, ExerciseTask.model_validate_json(row[0]), teacher) for row in rows]

    def update(
        self,
        cid: str,
        teacher: str,
        record_id: str,
        request: ExerciseReview | ExerciseAdoption,
    ) -> ExerciseRecord:
        self.store.get_classroom(teacher, cid)
        failure: StoreError | None = None
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body FROM exercise_sets WHERE id=? AND classroom_id=?", (record_id, cid)
            ).fetchone()
            if not row:
                raise StoreError(404, "练习不存在")
            record = ExerciseRecord.model_validate_json(row[0])
            row = db.execute("SELECT body FROM exercise_tasks WHERE id=?", (record.task_id,)).fetchone()
            record = self._refresh(db, ExerciseTask.model_validate_json(row[0]), teacher).exercise_set
            if record.status == "stale":
                failure = StoreError(409, "练习依据已过期")
            elif record.revision != request.expected_revision:
                failure = StoreError(409, "练习版本已变化，请重新读取")
            elif isinstance(request, ExerciseAdoption) and request.adopted and record.status != "confirmed":
                failure = StoreError(409, "只有教师确认后的练习才能采用")
            else:
                if isinstance(request, ExerciseReview):
                    record = record.model_copy(
                        update={
                            "exercises": request.exercises or record.exercises,
                            "status": request.action,
                            "reviewed_by": teacher,
                            "adopted": False,
                            "adopted_by": None,
                        }
                    )
                else:
                    record = record.model_copy(
                        update={
                            "adopted": request.adopted,
                            "adopted_by": teacher if request.adopted else None,
                        }
                    )
                record = record.model_copy(update={"revision": record.revision + 1})
                self._save_record(db, record)
                db.execute(
                    "INSERT INTO exercise_reviews VALUES (?, ?, ?)",
                    (record.id, record.revision, record.model_dump_json()),
                )
        if failure:
            raise failure
        return record
