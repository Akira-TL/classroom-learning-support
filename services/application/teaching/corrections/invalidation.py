"""仅访问已存在的业务表；不构造存储对象，不在事务内创建表。"""

import sqlite3

from ..exercises.models import ExerciseRecord, ExerciseTask
from ..learning.models import EvidenceRecord, EvidenceTask
from ..plans.models import PlanRecord, PlanTask
from ..reports.models import ParentReport
from ..students.models import ReportRecord
from .models import CorrectionImpact


def has_table(db: sqlite3.Connection, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def affected(db: sqlite3.Connection, cid: str, sid: str, segment: str, current_version: int) -> CorrectionImpact:
    evidence: list[EvidenceRecord] = []
    exercises: list[ExerciseRecord] = []
    plans: list[PlanRecord] = []
    students: list[ReportRecord] = []
    parents: list[ParentReport] = []
    if has_table(db, "evidence_records"):
        evidence = [
            EvidenceRecord.model_validate_json(row[0])
            for row in db.execute(
                "SELECT body FROM evidence_records WHERE classroom_id=?",
                (cid,),
            )
        ]
        evidence = [
            item
            for item in evidence
            if item.basis.session_id == sid
            and item.basis.segment_id == segment
            and item.basis.utterance_version != current_version
        ]
    eids = {item.id for item in evidence}
    if has_table(db, "exercise_sets"):
        exercises = [
            ExerciseRecord.model_validate_json(row[0])
            for row in db.execute(
                "SELECT body FROM exercise_sets WHERE classroom_id=?",
                (cid,),
            )
        ]
        exercises = [item for item in exercises if item.evidence_id in eids]
    if has_table(db, "plan_records"):
        plans = [
            PlanRecord.model_validate_json(row[0])
            for row in db.execute(
                "SELECT body FROM plan_records WHERE classroom_id=?",
                (cid,),
            )
        ]
        plans = [item for item in plans if item.evidence_id in eids]
    if has_table(db, "student_reports"):
        xids = {item.id for item in exercises}
        students = [
            ReportRecord.model_validate_json(row[0])
            for row in db.execute(
                "SELECT body FROM student_reports WHERE classroom_id=?",
                (cid,),
            )
        ]
        students = [item for item in students if item.exercise_set_id in xids]
    if has_table(db, "parent_reports"):
        parents = [
            ParentReport.model_validate_json(row[0])
            for row in db.execute(
                "SELECT body FROM parent_reports WHERE classroom_id=?",
                (cid,),
            )
        ]
        parents = [item for item in parents if item.content.evidence_id in eids]
    return CorrectionImpact(
        evidence_ids=[item.id for item in evidence if item.status != "stale"],
        exercise_ids=[item.id for item in exercises if item.status != "stale"],
        plan_ids=[item.id for item in plans if item.status != "stale"],
        student_report_ids=[item.id for item in students if item.status == "published"],
        parent_report_ids=[item.id for item in parents if item.status == "published"],
    )


def invalidate(db: sqlite3.Connection, cid: str, sid: str, segment: str, current_version: int) -> CorrectionImpact:
    impact = affected(db, cid, sid, segment, current_version)
    for eid in impact.evidence_ids:
        row = db.execute("SELECT body FROM evidence_records WHERE id=?", (eid,)).fetchone()
        record = EvidenceRecord.model_validate_json(row[0])
        record = record.model_copy(update={"status": "stale", "revision": record.revision + 1})
        db.execute("UPDATE evidence_records SET body=? WHERE id=?", (record.model_dump_json(), eid))
    if has_table(db, "evidence_tasks"):
        for row in db.execute("SELECT body FROM evidence_tasks WHERE classroom_id=?", (cid,)).fetchall():
            task = EvidenceTask.model_validate_json(row[0])
            if (
                task.basis.session_id == sid
                and task.basis.segment_id == segment
                and task.basis.utterance_version != current_version
                and task.status != "stale"
            ):
                task = task.model_copy(update={"status": "stale", "error": "发言依据已变化，需重新核验"})
                db.execute("UPDATE evidence_tasks SET body=? WHERE id=?", (task.model_dump_json(), task.id))
    for xid in impact.exercise_ids:
        row = db.execute("SELECT body FROM exercise_sets WHERE id=?", (xid,)).fetchone()
        exercise = ExerciseRecord.model_validate_json(row[0])
        exercise = exercise.model_copy(
            update={
                "status": "stale",
                "revision": exercise.revision + 1,
                "adopted": False,
                "adopted_by": None,
            }
        )
        db.execute("UPDATE exercise_sets SET body=? WHERE id=?", (exercise.model_dump_json(), xid))
    for pid in impact.plan_ids:
        row = db.execute("SELECT body FROM plan_records WHERE id=?", (pid,)).fetchone()
        plan = PlanRecord.model_validate_json(row[0])
        plan = plan.model_copy(
            update={
                "status": "stale",
                "revision": plan.revision + 1,
                "adopted": False,
                "adopted_by": None,
            }
        )
        db.execute("UPDATE plan_records SET body=? WHERE id=?", (plan.model_dump_json(), pid))
    eids: set[str] = set()
    if has_table(db, "evidence_records"):
        for row in db.execute("SELECT body FROM evidence_records WHERE classroom_id=?", (cid,)):
            evidence = EvidenceRecord.model_validate_json(row[0])
            if (
                evidence.basis.session_id == sid
                and evidence.basis.segment_id == segment
                and evidence.basis.utterance_version != current_version
            ):
                eids.add(evidence.id)
    if has_table(db, "exercise_tasks"):
        for row in db.execute("SELECT body FROM exercise_tasks WHERE classroom_id=?", (cid,)).fetchall():
            task = ExerciseTask.model_validate_json(row[0])
            if task.basis.id in eids and task.status != "stale":
                task = task.model_copy(update={"status": "stale", "error": "学习证据已失效"})
                db.execute("UPDATE exercise_tasks SET body=? WHERE id=?", (task.model_dump_json(), task.id))
    if has_table(db, "plan_tasks"):
        for row in db.execute("SELECT body FROM plan_tasks WHERE classroom_id=?", (cid,)).fetchall():
            task = PlanTask.model_validate_json(row[0])
            if task.basis.id in eids and task.status != "stale":
                task = task.model_copy(update={"status": "stale", "error": "学习证据已失效"})
                db.execute("UPDATE plan_tasks SET body=? WHERE id=?", (task.model_dump_json(), task.id))
    for rid in impact.student_report_ids:
        row = db.execute("SELECT body FROM student_reports WHERE id=?", (rid,)).fetchone()
        student = ReportRecord.model_validate_json(row[0])
        student = student.model_copy(update={"status": "stale", "revision": student.revision + 1})
        db.execute("UPDATE student_reports SET body=? WHERE id=?", (student.model_dump_json(), rid))
    for rid in impact.parent_report_ids:
        row = db.execute("SELECT body FROM parent_reports WHERE id=?", (rid,)).fetchone()
        parent = ParentReport.model_validate_json(row[0])
        parent = parent.model_copy(update={"status": "stale", "revision": parent.revision + 1})
        db.execute("UPDATE parent_reports SET body=? WHERE id=?", (parent.model_dump_json(), rid))
    return impact
