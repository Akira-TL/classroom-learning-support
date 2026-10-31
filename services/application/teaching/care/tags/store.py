import sqlite3
from uuid import uuid4

from ...audio.media import AudioAsset
from ...classroom.storage import SQLiteStore, StoreError
from .models import TagBatch, TagImport


class TagStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        with store.connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS care_tag_batches "
                       "(id TEXT PRIMARY KEY,classroom_id TEXT NOT NULL,teacher_id TEXT NOT NULL,body TEXT NOT NULL)")

    def listing(self, db: sqlite3.Connection, teacher: str, cid: str | None = None) -> list[TagBatch]:
        if cid:
            self.store._authorized(db, teacher, cid)
        rows = db.execute("SELECT b.body FROM care_tag_batches b JOIN classrooms c ON c.id=b.classroom_id "
                          "WHERE b.teacher_id=?", (teacher,)).fetchall()
        result = [item for row in rows if (item := TagBatch.model_validate_json(row[0]))
                  and (cid is None or item.classroom_id == cid)]
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='audio_assets'").fetchone():
            result = [item.model_copy(update={"audio_asset": self.audio_asset(db, item)}) for item in result]
        return result

    @staticmethod
    def audio_asset(db: sqlite3.Connection, batch: TagBatch) -> AudioAsset | None:
        row = db.execute("SELECT body FROM audio_assets WHERE classroom_id=? AND session_id=?",
                         (batch.classroom_id, batch.session_id)).fetchone()
        return AudioAsset.model_validate_json(row[0]) if row else None

    def save(self, cid: str, teacher: str, request: TagImport,
             identity: str | None = None, expected_revision: int | None = None) -> TagBatch:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            classroom = self.store._authorized(db, teacher, cid)
            if request.student_id not in classroom.students:
                raise StoreError(422, "标签学生不在课堂名单中")
            records = self.listing(db, teacher)
            previous = next((item for item in records if item.id == identity and item.classroom_id == cid), None)
            if identity and (not previous or previous.revision != expected_revision):
                raise StoreError(409, "标签记录版本已变化或不存在")
            payload = TagImport.model_validate(request.model_dump(exclude={"expected_revision"}))
            for existing in records:
                if existing.id == identity:
                    continue
                if existing.import_id == payload.import_id:
                    if existing.classroom_id != cid:
                        raise StoreError(409, "该导入标识已用于其他课堂，请使用原课堂记录")
                    if TagImport.model_validate(existing.model_dump(include=set(TagImport.model_fields))) == payload:
                        return existing
                    raise StoreError(409, "同一导入标识不能用于不同标注，请修改原记录并递增版本")
                if (existing.classroom_id == cid and existing.student_id == payload.student_id
                        and existing.session_id == payload.session_id):
                    raise StoreError(409, "同一课堂、学生和采集会话已有标注，请用PUT更新原记录，不能重复累计次数或时长")
            record = TagBatch(**payload.model_dump(), id=identity or uuid4().hex, classroom_id=cid, teacher_id=teacher,
                              revision=previous.revision + 1 if previous else 1)
            db.execute("INSERT OR REPLACE INTO care_tag_batches VALUES (?,?,?,?)",
                       (record.id, cid, teacher, record.model_dump_json()))
            return record
