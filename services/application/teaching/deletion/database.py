import sqlite3

from .models import Resource

DIRECT_TABLES = (
    "care_observations",
    "care_reports",
    "audio_assets",
    "input_frames",
    "input_sessions",
    "speech_events",
    "utterances",
    "speech_reviews",
    "evidence_tasks",
    "evidence_records",
    "exercise_tasks",
    "exercise_sets",
    "manual_exercise_sets",
    "plan_tasks",
    "plan_records",
    "student_reports",
    "student_feedback",
    "parent_reports",
    "parent_questions",
    "teacher_exports",
    "corrections",
)
HISTORY_TABLES = (
    ("evidence_records", "evidence_reviews", "evidence_id"),
    ("exercise_sets", "exercise_reviews", "record_id"),
    ("manual_exercise_sets", "manual_exercise_reviews", "record_id"),
    ("plan_records", "plan_reviews", "record_id"),
    ("student_feedback", "student_feedback_history", "feedback_id"),
)


def clear_database(db: sqlite3.Connection, cid: str) -> list[Resource]:
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    resources: list[Resource] = []
    if "audio_assets" in tables:
        resources.extend(
            Resource(kind="audio", id=row[0])
            for row in db.execute(
                "SELECT asset_id FROM audio_assets WHERE classroom_id=?",
                (cid,),
            )
        )
    if "teacher_exports" in tables:
        ids = [row[0] for row in db.execute("SELECT id FROM teacher_exports WHERE classroom_id=?", (cid,))]
        resources.extend(Resource(kind="export", id=identity) for identity in ids)
        if "export_status" in tables:
            db.executemany(
                "UPDATE export_status SET status='deleted',revision=revision+1 WHERE id=?",
                ((identity,) for identity in ids),
            )
    for source, history, column in HISTORY_TABLES:
        if source in tables and history in tables:
            ids = [row[0] for row in db.execute(f"SELECT id FROM {source} WHERE classroom_id=?", (cid,))]
            db.executemany(f"DELETE FROM {history} WHERE {column}=?", ((identity,) for identity in ids))
    for table in DIRECT_TABLES:
        if table in tables:
            db.execute(f"DELETE FROM {table} WHERE classroom_id=?", (cid,))
    db.execute("DELETE FROM classrooms WHERE id=?", (cid,))
    return resources
