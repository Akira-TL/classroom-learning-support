import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from ..classroom.storage import StoreError
from .models import (
    ReportPreview,
    ReportRecord,
    ReportSummary,
    ReportView,
    RevokeReport,
    StudentPublish,
    StudentPublishPreview,
)
from .store import StudentStore


class Publishing:
    def __init__(self, base: StudentStore) -> None:
        self.base = base

    def preview(self, cid: str, teacher: str, request: StudentPublishPreview) -> ReportPreview:
        with self.base.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            exercise = self.base.exercise(db, cid, teacher, request)
            return ReportPreview(student_id=request.student_id, feedback=request.feedback, exercises=exercise.exercises)

    def publish(self, cid: str, teacher: str, request: StudentPublish) -> ReportView:
        self.base.store.get_classroom(teacher, cid)
        fingerprint = hashlib.sha256(request.model_dump_json(exclude={"idempotency_key"}).encode()).hexdigest()
        with self.base.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT body,request_hash FROM student_reports WHERE classroom_id=? AND request_key=?",
                (cid, request.idempotency_key),
            ).fetchone()
            if row:
                if row[1] != fingerprint:
                    raise StoreError(409, "相同幂等标识不能发布不同内容")
                record = self.base.refresh(db, ReportRecord.model_validate_json(row[0]))
            else:
                exercise = self.base.exercise(db, cid, teacher, request)
                record = ReportRecord(
                    id=uuid4().hex,
                    classroom_id=cid,
                    student_id=request.student_id,
                    teacher_id=teacher,
                    revision=1,
                    published_at=datetime.now(UTC),
                    status="published",
                    exercise_set_id=exercise.id,
                    exercise_revision=exercise.revision,
                    feedback=request.feedback,
                    exercises=exercise.exercises,
                )
                db.execute(
                    "INSERT INTO student_reports VALUES (?, ?, ?, ?, ?, ?)",
                    (record.id, cid, record.student_id, record.model_dump_json(), request.idempotency_key, fingerprint),
                )
        return self.base.view(record)

    def revoke(self, cid: str, teacher: str, rid: str, request: RevokeReport) -> ReportSummary:
        self.base.store.get_classroom(teacher, cid)
        with self.base.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self.base.record(db, rid)
            if record.classroom_id != cid:
                raise StoreError(404, "报告不属于本课堂")
            if record.revision != request.expected_revision:
                raise StoreError(409, "报告版本已变化")
            record = record.model_copy(update={"status": "revoked", "revision": record.revision + 1})
            self.base.save(db, record)
        return self.base.summary(record)
