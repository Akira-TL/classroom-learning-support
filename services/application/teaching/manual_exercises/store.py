import sqlite3
from uuid import uuid4

from ..classroom.storage import SQLiteStore, StoreError
from .models import CreateManualExercises, ManualAdoption, ManualExerciseRecord, ManualHistory, ManualReview


class ManualExerciseStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS manual_exercise_sets (
                    id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    request_body TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(classroom_id, request_key)
                );
                CREATE INDEX IF NOT EXISTS manual_exercises_classroom ON manual_exercise_sets(classroom_id);
                CREATE TABLE IF NOT EXISTS manual_exercise_reviews (
                    record_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(record_id, revision)
                );
            """)

    @staticmethod
    def authorize(db: sqlite3.Connection, cid: str, teacher: str) -> None:
        row = db.execute("SELECT teacher_id FROM classrooms WHERE id=?", (cid,)).fetchone()
        if row is None:
            raise StoreError(404, "课堂不存在，不能读写人工练习")
        if row[0] != teacher:
            raise StoreError(403, "无权访问该课堂人工练习")

    @staticmethod
    def history(db: sqlite3.Connection, record: ManualExerciseRecord, actor: str, action: str) -> None:
        history = ManualHistory(actor=actor, action=action, record=record)
        db.execute(
            "INSERT INTO manual_exercise_reviews VALUES (?, ?, ?)",
            (record.id, record.revision, history.model_dump_json()),
        )

    def create(self, cid: str, teacher: str, request: CreateManualExercises) -> ManualExerciseRecord:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.authorize(db, cid, teacher)
            row = db.execute(
                "SELECT request_body,body FROM manual_exercise_sets WHERE classroom_id=? AND request_key=?",
                (cid, request.idempotency_key),
            ).fetchone()
            if row:
                if row[0] != request.model_dump_json():
                    raise StoreError(409, "相同幂等标识不能提交不同人工初稿")
                return ManualExerciseRecord.model_validate_json(row[1])
            record = ManualExerciseRecord(
                id=uuid4().hex,
                classroom_id=cid,
                exercises=request.exercises,
                initial_exercises=request.exercises,
                created_by=teacher,
            )
            db.execute(
                "INSERT INTO manual_exercise_sets VALUES (?, ?, ?, ?, ?)",
                (record.id, cid, request.idempotency_key, request.model_dump_json(), record.model_dump_json()),
            )
            self.history(db, record, teacher, "created")
            return record

    def list(self, cid: str, teacher: str) -> list[ManualExerciseRecord]:
        with self.store.connection() as db:
            db.execute("BEGIN")
            self.authorize(db, cid, teacher)
            rows = db.execute("SELECT body FROM manual_exercise_sets WHERE classroom_id=? ORDER BY rowid", (cid,))
            return [ManualExerciseRecord.model_validate_json(row[0]) for row in rows]

    def update(
        self, cid: str, teacher: str, identity: str, request: ManualReview | ManualAdoption
    ) -> ManualExerciseRecord:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.authorize(db, cid, teacher)
            row = db.execute(
                "SELECT body FROM manual_exercise_sets WHERE id=? AND classroom_id=?", (identity, cid)
            ).fetchone()
            if not row:
                raise StoreError(404, "人工练习不存在")
            old = ManualExerciseRecord.model_validate_json(row[0])
            if old.revision != request.expected_revision:
                raise StoreError(409, "人工练习版本已变化，请刷新并重新核对")
            if isinstance(request, ManualReview):
                record = ManualExerciseRecord(
                    **old.model_dump(
                        exclude={"exercises", "status", "reviewed_by", "adopted", "adopted_by", "revision"}
                    ),
                    exercises=request.exercises or old.exercises,
                    status=request.action,
                    reviewed_by=teacher,
                    adopted=False,
                    adopted_by=None,
                    revision=old.revision + 1,
                )
                action = request.action
            else:
                if request.adopted and old.status != "confirmed":
                    raise StoreError(409, "人工练习须经教师确认后才能采用")
                record = ManualExerciseRecord(
                    **old.model_dump(exclude={"adopted", "adopted_by", "revision"}),
                    adopted=request.adopted,
                    adopted_by=teacher if request.adopted else None,
                    revision=old.revision + 1,
                )
                action = "adopted" if request.adopted else "unadopted"
            db.execute("UPDATE manual_exercise_sets SET body=? WHERE id=?", (record.model_dump_json(), identity))
            self.history(db, record, teacher, action)
            return record
