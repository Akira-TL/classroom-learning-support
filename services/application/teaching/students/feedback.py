import hashlib
from uuid import uuid4

from ..classroom.storage import StoreError
from .models import FeedbackRecord, HandleFeedback, StudentFeedbackRequest
from .store import StudentStore


class Feedback:
    def __init__(self, base: StudentStore) -> None:
        self.base = base

    def submit(self, rid: str, student: str, request: StudentFeedbackRequest) -> FeedbackRecord:
        fingerprint = hashlib.sha256(request.model_dump_json(exclude={"idempotency_key"}).encode()).hexdigest()
        failure: StoreError | None = None
        result: FeedbackRecord | None = None
        with self.base.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self.base.refresh(db, self.base.student_record(db, rid, student))
            row = db.execute(
                "SELECT body,request_hash FROM student_feedback WHERE report_id=? AND student_id=? AND request_key=?",
                (rid, student, request.idempotency_key),
            ).fetchone()
            if row:
                if row[1] != fingerprint:
                    failure = StoreError(409, "相同幂等标识不能提交不同反馈")
                else:
                    result = FeedbackRecord.model_validate_json(row[0])
            elif record.status != "published":
                failure = StoreError(410, "旧报告不接受新反馈，请等待新版")
            else:
                result = FeedbackRecord(
                    id=uuid4().hex,
                    classroom_id=record.classroom_id,
                    report_id=rid,
                    report_revision=record.revision,
                    student_id=student,
                    kind=request.kind,
                    text=request.text,
                )
                db.execute(
                    "INSERT INTO student_feedback VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.id,
                        record.classroom_id,
                        rid,
                        student,
                        result.model_dump_json(),
                        request.idempotency_key,
                        fingerprint,
                    ),
                )
        if failure:
            raise failure
        return result

    def list_student(self, rid: str, student: str) -> list[FeedbackRecord]:
        with self.base.store.connection() as db:
            self.base.student_record(db, rid, student)
            rows = db.execute(
                "SELECT body FROM student_feedback WHERE report_id=? AND student_id=? ORDER BY rowid", (rid, student)
            ).fetchall()
        return [FeedbackRecord.model_validate_json(row[0]) for row in rows]

    def list_teacher(self, cid: str, teacher: str) -> list[FeedbackRecord]:
        self.base.store.get_classroom(teacher, cid)
        with self.base.store.connection() as db:
            rows = db.execute(
                "SELECT body FROM student_feedback WHERE classroom_id=? ORDER BY rowid", (cid,)
            ).fetchall()
        return [FeedbackRecord.model_validate_json(row[0]) for row in rows]

    def handle(self, cid: str, teacher: str, fid: str, request: HandleFeedback) -> FeedbackRecord:
        self.base.store.get_classroom(teacher, cid)
        with self.base.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT body FROM student_feedback WHERE id=? AND classroom_id=?", (fid, cid)).fetchone()
            if not row:
                raise StoreError(404, "反馈不存在")
            old = FeedbackRecord.model_validate_json(row[0])
            if old.revision != request.expected_revision:
                raise StoreError(409, "反馈版本已变化")
            result = old.model_copy(
                update={
                    "revision": old.revision + 1,
                    "status": request.status,
                    "response": request.response,
                    "handled_by": teacher,
                }
            )
            db.execute(
                "INSERT INTO student_feedback_history VALUES (?, ?, ?)", (fid, old.revision, old.model_dump_json())
            )
            db.execute("UPDATE student_feedback SET body=? WHERE id=?", (result.model_dump_json(), fid))
        return result
