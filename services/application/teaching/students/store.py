import sqlite3

from ..audio.models import Utterance
from ..classroom.storage import SQLiteStore, StoreError
from ..exercises.models import ExerciseRecord
from ..learning.models import EvidenceRecord
from ..learning.store import EvidenceStore
from ..models import StrictModel
from .models import FeedbackRecord, ReportRecord, ReportSummary, ReportView, StudentPublishPreview


class FeedbackSource(StrictModel):
    original_report_revision: int
    session_id: str
    segment_id: str
    current_utterance_version: int
    original_student_id: str
    current_student_alias: str | None
    current_question_id: str | None


class StudentStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self.evidence = EvidenceStore(store)
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS student_reports (
                    id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, student_id TEXT NOT NULL, body TEXT NOT NULL,
                    request_key TEXT NOT NULL, request_hash TEXT NOT NULL, UNIQUE(classroom_id,request_key)
                );
                CREATE TABLE IF NOT EXISTS student_feedback (
                    id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, report_id TEXT NOT NULL,
                    student_id TEXT NOT NULL, body TEXT NOT NULL, request_key TEXT NOT NULL, request_hash TEXT NOT NULL,
                    UNIQUE(report_id,student_id,request_key)
                );
                CREATE TABLE IF NOT EXISTS student_feedback_history (
                    feedback_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
                    PRIMARY KEY(feedback_id,revision)
                );
            """)

    def exercise(
        self,
        db: sqlite3.Connection,
        cid: str,
        teacher: str,
        request: StudentPublishPreview,
    ) -> ExerciseRecord:
        owner = db.execute("SELECT teacher_id FROM classrooms WHERE id=?", (cid,)).fetchone()
        if not owner:
            raise StoreError(404, "课堂不存在")
        if owner[0] != teacher:
            raise StoreError(403, "无权管理此课堂")
        row = db.execute(
            "SELECT body FROM exercise_sets WHERE id=? AND classroom_id=?", (request.exercise_set_id, cid)
        ).fetchone()
        if not row:
            raise StoreError(404, "练习不存在")
        exercise = ExerciseRecord.model_validate_json(row[0])
        if exercise.status != "confirmed" or exercise.revision != request.expected_exercise_revision:
            raise StoreError(409, "练习须为当前教师已确认版本")
        evidence = self.evidence.require_confirmed(db, cid, teacher, exercise.evidence_id, exercise.evidence_revision)
        if evidence.basis.context.student_alias != request.student_id:
            raise StoreError(422, "接收学生必须与学习证据的学生一致")
        return exercise

    def record(self, db: sqlite3.Connection, rid: str) -> ReportRecord:
        row = db.execute("SELECT body FROM student_reports WHERE id=?", (rid,)).fetchone()
        if not row:
            raise StoreError(404, "报告不存在")
        return ReportRecord.model_validate_json(row[0])

    def refresh(self, db: sqlite3.Connection, record: ReportRecord) -> ReportRecord:
        if record.status == "published":
            try:
                self.exercise(
                    db,
                    record.classroom_id,
                    record.teacher_id,
                    StudentPublishPreview(
                        exercise_set_id=record.exercise_set_id,
                        expected_exercise_revision=record.exercise_revision,
                        student_id=record.student_id,
                        feedback=record.feedback,
                    ),
                )
            except StoreError:
                record = record.model_copy(update={"status": "stale", "revision": record.revision + 1})
                self.save(db, record)
        return record

    def save(self, db: sqlite3.Connection, record: ReportRecord) -> None:
        db.execute("UPDATE student_reports SET body=? WHERE id=?", (record.model_dump_json(), record.id))

    def summary(self, record: ReportRecord) -> ReportSummary:
        return ReportSummary.model_validate(record.model_dump(include=set(ReportSummary.model_fields)))

    def view(self, record: ReportRecord) -> ReportView:
        if record.status != "published":
            raise StoreError(410, "报告已撤回或依据失效，等待教师发布新版")
        return ReportView.model_validate(record.model_dump(include=set(ReportView.model_fields)))

    def student_record(self, db: sqlite3.Connection, rid: str, student: str) -> ReportRecord:
        record = self.record(db, rid)
        if record.student_id != student:
            raise StoreError(403, "无权访问其他学生报告")
        return record

    def get(self, rid: str, student: str) -> ReportView:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self.refresh(db, self.student_record(db, rid, student))
        return self.view(record)

    def list_student(self, student: str) -> list[ReportSummary]:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT body FROM student_reports WHERE student_id=? ORDER BY rowid", (student,)
            ).fetchall()
            return [self.summary(self.refresh(db, ReportRecord.model_validate_json(row[0]))) for row in rows]

    def list_teacher(self, cid: str, teacher: str) -> list[ReportSummary]:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT body FROM student_reports WHERE classroom_id=? ORDER BY rowid", (cid,)).fetchall()
            return [self.summary(self.refresh(db, ReportRecord.model_validate_json(row[0]))) for row in rows]

    def feedback_source(self, cid: str, teacher: str, feedback_id: str) -> FeedbackSource:
        self.store.get_classroom(teacher, cid)
        with self.store.connection() as db:
            row = db.execute(
                "SELECT report_id,student_id,body FROM student_feedback WHERE id=? AND classroom_id=?",
                (feedback_id, cid),
            ).fetchone()
            if not row:
                raise StoreError(404, "反馈不存在")
            feedback = FeedbackRecord.model_validate_json(row[2])
            report = self.record(db, row[0])
            row = db.execute(
                "SELECT body FROM exercise_sets WHERE id=? AND classroom_id=?", (report.exercise_set_id, cid)
            ).fetchone()
            if not row:
                raise StoreError(404, "原练习来源不存在")
            exercise = ExerciseRecord.model_validate_json(row[0])
            row = db.execute(
                "SELECT body FROM evidence_records WHERE id=? AND classroom_id=?", (exercise.evidence_id, cid)
            ).fetchone()
            if not row:
                raise StoreError(404, "原学习证据来源不存在")
            evidence = EvidenceRecord.model_validate_json(row[0])
            basis = evidence.basis
            row = db.execute(
                "SELECT body FROM utterances WHERE classroom_id=? AND session_id=? AND segment_id=?",
                (cid, basis.session_id, basis.segment_id),
            ).fetchone()
            if not row:
                raise StoreError(404, "原发言片段不存在")
            current = Utterance.model_validate_json(row[0])
            return FeedbackSource(
                original_report_revision=feedback.report_revision,
                session_id=basis.session_id,
                segment_id=basis.segment_id,
                current_utterance_version=current.version,
                original_student_id=feedback.student_id,
                current_student_alias=current.student_alias,
                current_question_id=current.question_id,
            )
