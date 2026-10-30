"""事务性 SQLite 保存；课堂归属与版本在同一事务中校验。"""

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .classrooms import Classroom, ClassroomContent, CreateClassroom, UpdateClassroom


class StoreError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS classrooms (
                    id TEXT PRIMARY KEY, teacher_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    payload TEXT NOT NULL, creation_key TEXT NOT NULL, creation_hash TEXT NOT NULL,
                    UNIQUE (teacher_id, creation_key)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at INTEGER NOT NULL
                );
            """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_classroom(self, teacher_id: str, request: CreateClassroom) -> Classroom:
        content = ClassroomContent.model_validate(request.model_dump(exclude={"idempotency_key"}))
        fingerprint = hashlib.sha256(content.model_dump_json().encode()).hexdigest()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, creation_hash FROM classrooms WHERE teacher_id=? AND creation_key=?",
                (teacher_id, request.idempotency_key),
            ).fetchone()
            if row:
                if row["creation_hash"] != fingerprint:
                    raise StoreError(409, "相同幂等标识不能用于不同课堂内容")
                return Classroom.model_validate_json(row["payload"])
            classroom = Classroom(id=uuid4().hex, teacher_id=teacher_id, revision=1, **content.model_dump())
            connection.execute(
                "INSERT INTO classrooms VALUES (?, ?, ?, ?, ?, ?)",
                (classroom.id, teacher_id, 1, classroom.model_dump_json(), request.idempotency_key, fingerprint),
            )
        return classroom

    def get_classroom(self, teacher_id: str, classroom_id: str) -> Classroom:
        with self.connection() as connection:
            return self._authorized(connection, teacher_id, classroom_id)

    def _authorized(self, connection: sqlite3.Connection, teacher_id: str, classroom_id: str) -> Classroom:
        row = connection.execute("SELECT teacher_id, payload FROM classrooms WHERE id=?", (classroom_id,)).fetchone()
        if row is None:
            raise StoreError(404, "课堂不存在")
        if row["teacher_id"] != teacher_id:
            raise StoreError(403, "无权访问该课堂")
        return Classroom.model_validate_json(row["payload"])

    def list_classrooms(self, teacher_id: str) -> list[Classroom]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM classrooms WHERE teacher_id=? ORDER BY rowid DESC",
                (teacher_id,),
            ).fetchall()
        return [Classroom.model_validate_json(row["payload"]) for row in rows]

    def update_classroom(self, teacher_id: str, classroom_id: str, request: UpdateClassroom) -> Classroom:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._authorized(connection, teacher_id, classroom_id)
            if existing.revision != request.expected_revision:
                raise StoreError(409, "课堂版本已变化，请重新读取")
            updated = Classroom(
                **request.model_dump(exclude={"expected_revision"}),
                id=classroom_id,
                teacher_id=teacher_id,
                revision=existing.revision + 1,
            )
            connection.execute(
                "UPDATE classrooms SET revision=?, payload=? WHERE id=?",
                (updated.revision, updated.model_dump_json(), classroom_id),
            )
        return updated
