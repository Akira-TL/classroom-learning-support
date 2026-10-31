import sqlite3
from uuid import uuid4

from pydantic import ValidationError

from ..audio.models import Utterance
from ..classroom.storage import SQLiteStore, StoreError
from .models import AcousticMeasurements, CareReport, Observation, ObservationInput


def require_source(db: sqlite3.Connection, store: SQLiteStore, cid: str, teacher: str,
                   payload: ObservationInput) -> Utterance:
    classroom = store._authorized(db, teacher, cid)
    row = db.execute("SELECT body FROM utterances WHERE classroom_id=? AND session_id=? AND segment_id=?",
                     (cid, payload.session_id, payload.segment_id)).fetchone()
    if not row:
        raise StoreError(409, "来源发言不存在或已删除")
    source = Utterance.model_validate_json(row[0])
    if (source.version != payload.expected_utterance_version or source.phase in {"partial", "withdraw"}
            or source.identity_review != "confirmed" or source.text_review != "confirmed"
            or source.student_alias != payload.student_id or payload.student_id not in classroom.students):
        raise StoreError(409, "发言版本或学生归属尚未核验，请重新核验来源")
    if classroom.date != payload.observed_on:
        raise StoreError(422, "观察日期须与来源课堂日期一致")
    return source


def current(db: sqlite3.Connection, store: SQLiteStore, record: Observation) -> bool:
    try:
        require_source(db, store, record.classroom_id, record.teacher_id, record)
        return True
    except StoreError:
        return False


def measurements(source: Utterance) -> AcousticMeasurements | None:
    diagnostics = source.native_event.diagnostics if source.native_event else None
    raw = diagnostics.get("acoustic_measurements") if diagnostics else None
    if raw is None:
        return None
    try:
        return AcousticMeasurements.model_validate(raw)
    except ValidationError:
        return None


class CareStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS care_observations
                (id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, teacher_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS care_reports
                (id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, teacher_id TEXT NOT NULL, body TEXT NOT NULL);
            """)

    def list_observations(self, db: sqlite3.Connection, teacher: str, cid: str | None = None) -> list[Observation]:
        if cid:
            self.store._authorized(db, teacher, cid)
        rows = db.execute("SELECT body FROM care_observations WHERE teacher_id=?", (teacher,)).fetchall()
        observations = [Observation.model_validate_json(row[0]) for row in rows]
        return [item.model_copy(update={"source_current": current(db, self.store, item)}) for item in observations
                if cid is None or item.classroom_id == cid]

    def save_observation(self, cid: str, teacher: str, payload: ObservationInput,
                         identity: str | None = None, expected: int | None = None) -> Observation:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            source = require_source(db, self.store, cid, teacher, payload)
            for saved in self.list_observations(db, teacher, cid):
                if (saved.id != identity and saved.session_id == payload.session_id
                        and saved.segment_id == payload.segment_id and saved.student_id == payload.student_id):
                    raise StoreError(409, "该发言已有观察记录，请修改原记录，不能重复计为多个样本")
            revision = 1
            if identity:
                row = db.execute("SELECT body FROM care_observations WHERE id=? AND classroom_id=? AND teacher_id=?",
                                 (identity, cid, teacher)).fetchone()
                if not row:
                    raise StoreError(404, "观察记录不存在")
                old = Observation.model_validate_json(row[0])
                if old.revision != expected:
                    raise StoreError(409, "观察记录已变化，请刷新")
                revision = old.revision + 1
            content = ObservationInput.model_validate(payload.model_dump(exclude={"expected_revision"}))
            measured = measurements(source)
            record = Observation(
                **content.model_dump(), id=identity or uuid4().hex, classroom_id=cid, teacher_id=teacher,
                revision=revision, measurements=measured,
                measurement_note="已保留上游可靠测量及其方法；须结合采集条件比较" if measured
                else "上游尚未提供可核查的可靠声学测量",
            )
            db.execute("INSERT OR REPLACE INTO care_observations VALUES (?,?,?,?)",
                       (record.id, cid, teacher, record.model_dump_json()))
            return record

    @staticmethod
    def report(db: sqlite3.Connection, cid: str, teacher: str, rid: str) -> CareReport:
        row = db.execute("SELECT body FROM care_reports WHERE id=? AND classroom_id=? AND teacher_id=?",
                         (rid, cid, teacher)).fetchone()
        if not row:
            raise StoreError(404, "关怀记录不存在")
        return CareReport.model_validate_json(row[0])

    @staticmethod
    def write_report(db: sqlite3.Connection, report: CareReport) -> None:
        db.execute("INSERT OR REPLACE INTO care_reports VALUES (?,?,?,?)",
                   (report.id, report.classroom_id, report.teacher_id, report.model_dump_json()))
