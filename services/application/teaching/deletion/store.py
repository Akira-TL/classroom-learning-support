import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from ..classroom.classrooms import Classroom
from ..classroom.storage import SQLiteStore, StoreError
from .database import clear_database
from .models import DeleteClassroom, DeletionTask, DeletionView, Resource
from .resources import remove_resource


class DeletionStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        with store.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS classroom_deletions "
                "(id TEXT PRIMARY KEY, classroom_id TEXT UNIQUE NOT NULL, teacher_id TEXT NOT NULL, "
                "request_key TEXT NOT NULL, request_hash TEXT NOT NULL, body TEXT NOT NULL)"
            )

    def view(self, task: DeletionTask) -> DeletionView:
        return DeletionView(
            id=task.id,
            classroom_id=task.classroom_id,
            revision=task.revision,
            created_at=task.created_at,
            local_status=task.local_status,
            local_complete=task.local_status == "complete",
            external_status=task.external_status,
            remaining_files=len(task.remaining),
            error=task.error,
        )

    def create(self, cid: str, teacher: str, request: DeleteClassroom) -> DeletionView:
        fingerprint = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        with self.store.connection() as db:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body,request_key,request_hash FROM classroom_deletions WHERE classroom_id=?", (cid,)
            ).fetchone()
            if row:
                task = DeletionTask.model_validate_json(row[0])
                if task.teacher_id != teacher:
                    raise StoreError(403, "无权查询此删除操作")
                if row[1] != request.idempotency_key:
                    raise StoreError(410, "课堂已删除，请查询原删除任务")
                if row[2] != fingerprint:
                    raise StoreError(409, "相同幂等标识不能用于不同删除请求")
            else:
                row = db.execute("SELECT payload FROM classrooms WHERE id=?", (cid,)).fetchone()
                if not row:
                    raise StoreError(404, "课堂不存在")
                classroom = Classroom.model_validate_json(row[0])
                if classroom.teacher_id != teacher:
                    raise StoreError(403, "无权删除此课堂")
                if classroom.revision != request.expected_revision:
                    raise StoreError(409, "课堂版本已变化，请重新读取")
                if classroom.title != request.confirmation:
                    raise StoreError(422, "请准确输入课堂名称以确认删除")
                resources = clear_database(db, cid)
                task = DeletionTask(
                    id=uuid4().hex,
                    classroom_id=cid,
                    teacher_id=teacher,
                    created_at=datetime.now(UTC),
                    remaining=resources,
                )
                db.execute(
                    "INSERT INTO classroom_deletions VALUES (?, ?, ?, ?, ?, ?)",
                    (task.id, cid, teacher, request.idempotency_key, fingerprint, task.model_dump_json()),
                )
        return self.retry(task.id, teacher)

    def get(self, identity: str, teacher: str) -> DeletionView:
        with self.store.connection() as db:
            row = db.execute("SELECT body FROM classroom_deletions WHERE id=?", (identity,)).fetchone()
            if not row:
                raise StoreError(404, "删除任务不存在")
            task = DeletionTask.model_validate_json(row[0])
            if task.teacher_id != teacher:
                raise StoreError(403, "无权查询此删除任务")
        return self.view(task)

    def retry(self, identity: str, teacher: str) -> DeletionView:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM classroom_deletions WHERE id=?", (identity,)).fetchone()
            if not row:
                raise StoreError(404, "删除任务不存在")
            task = DeletionTask.model_validate_json(row[0])
            if task.teacher_id != teacher:
                raise StoreError(403, "无权重试此删除任务")
            if task.local_status == "complete":
                return self.view(task)
            remaining: list[Resource] = []
            for resource in task.remaining:
                try:
                    remove_resource(self.store.path.parent, resource)
                except OSError:
                    remaining.append(resource)
            task = task.model_copy(
                update={
                    "revision": task.revision + 1,
                    "remaining": remaining,
                    "local_status": "failed" if remaining else "complete",
                    "error": "部分本机文件清除失败，可重试；受控入口已经关闭" if remaining else None,
                }
            )
            db.execute("UPDATE classroom_deletions SET body=? WHERE id=?", (task.model_dump_json(), identity))
        return self.view(task)
