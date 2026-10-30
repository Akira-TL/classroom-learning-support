import sqlite3
from uuid import uuid4

from ..audio.models import Utterance
from ..audio.store import SpeechConflict, SpeechStore, require_classroom
from ..classroom.classrooms import Classroom
from ..classroom.storage import SQLiteStore, StoreError
from .invalidation import affected
from .models import CorrectionApply, CorrectionAssessment, CorrectionPreview, CorrectionResult


class CorrectionStore:
    def __init__(self, store: SQLiteStore, speech: SpeechStore) -> None:
        if store.path.resolve() != speech.path.resolve():
            raise ValueError("纠错与发言必须使用同一事务数据库")
        self.store, self.speech = store, speech
        with store.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS corrections "
                "(id TEXT PRIMARY KEY, classroom_id TEXT, request_key TEXT, body TEXT, "
                "UNIQUE(classroom_id, request_key))"
            )

    def _check(self, db: sqlite3.Connection, cid: str, teacher: str, request: CorrectionPreview) -> Utterance:
        require_classroom(db, cid)
        row = db.execute("SELECT payload FROM classrooms WHERE id=?", (cid,)).fetchone()
        if not row:
            raise StoreError(404, "课堂不存在")
        classroom = Classroom.model_validate_json(row[0])
        if classroom.teacher_id != teacher:
            raise StoreError(403, "无权管理此课堂")
        if request.review.student_alias and request.review.student_alias not in classroom.students:
            raise StoreError(422, "学生不在本课堂名单")
        if request.review.question_id and request.review.question_id not in {q.id for q in classroom.questions}:
            raise StoreError(422, "题目不属于本课堂")
        row = db.execute(
            "SELECT body FROM utterances WHERE classroom_id=? AND session_id=? AND segment_id=?",
            (cid, request.session_id, request.segment_id),
        ).fetchone()
        if not row:
            raise StoreError(404, "发言不存在")
        current = Utterance.model_validate_json(row[0])
        if current.version != request.review.expected_version:
            raise StoreError(409, "发言已变化，请重新预览")
        if current.phase in {"partial", "withdraw"} and "confirmed" in {
            request.review.text_review,
            request.review.identity_review,
            request.review.question_review,
        }:
            raise StoreError(409, "临时或撤回的发言不能确认")
        return current

    def preview(self, cid: str, teacher: str, request: CorrectionPreview) -> CorrectionAssessment:
        with self.store.connection() as db:
            db.execute("BEGIN")
            current = self._check(db, cid, teacher, request)
            return CorrectionAssessment(
                current=current,
                impact=affected(
                    db,
                    cid,
                    request.session_id,
                    request.segment_id,
                    current.version + 1,
                ),
            )

    def apply(self, cid: str, teacher: str, request: CorrectionApply) -> CorrectionResult:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            require_classroom(db, cid)
            row = db.execute(
                "SELECT body FROM corrections WHERE classroom_id=? AND request_key=?", (cid, request.idempotency_key)
            ).fetchone()
            if row:
                old = CorrectionResult.model_validate_json(row[0])
                if old.request != request:
                    raise StoreError(409, "相同幂等标识不能用于不同纠错内容")
                return old
            current = self._check(db, cid, teacher, request)
            impact = affected(db, cid, request.session_id, request.segment_id, current.version + 1)
            try:
                updated = self.speech.review_in_transaction(
                    db,
                    cid,
                    request.session_id,
                    request.segment_id,
                    teacher,
                    request.review,
                )
            except SpeechConflict as error:
                raise StoreError(409, str(error)) from None
            result = CorrectionResult(
                id=uuid4().hex,
                classroom_id=cid,
                request=request,
                utterance=updated,
                impact=impact,
            )
            db.execute(
                "INSERT INTO corrections VALUES (?, ?, ?, ?)",
                (
                    result.id,
                    cid,
                    request.idempotency_key,
                    result.model_dump_json(),
                ),
            )
            return result
