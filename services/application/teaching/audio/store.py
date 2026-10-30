"""在 SQLite 事务中保存语音事件、独立核验与可重放的原始版本。"""

import sqlite3
from pathlib import Path

from .models import SpeechEvent, Utterance


class SpeechConflict(ValueError):
    pass


class SpeechStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS speech_events "
                "(classroom_id TEXT, session_id TEXT, event_id TEXT, body TEXT NOT NULL, "
                "PRIMARY KEY(classroom_id, session_id, event_id))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS utterances "
                "(classroom_id TEXT, session_id TEXT, segment_id TEXT, body TEXT NOT NULL, "
                "PRIMARY KEY(classroom_id, session_id, segment_id))"
            )

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def events(self, classroom_id: str) -> list[SpeechEvent]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT body FROM speech_events WHERE classroom_id=? ORDER BY rowid", (classroom_id,)
            ).fetchall()
        return [SpeechEvent.model_validate_json(row[0]) for row in rows]

    def timeline(self, classroom_id: str) -> list[Utterance]:
        with self.connect() as db:
            rows = db.execute("SELECT body FROM utterances WHERE classroom_id=?", (classroom_id,)).fetchall()
        return sorted((Utterance.model_validate_json(row[0]) for row in rows), key=lambda item: item.start_ms)

    def receive(self, classroom_id: str, event: SpeechEvent) -> bool:
        """返回是否记录新事件；重复事件不得更改已核验片段。"""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            key = (classroom_id, event.session_id, event.event_id)
            previous = db.execute(
                "SELECT body FROM speech_events WHERE classroom_id=? AND session_id=? AND event_id=?", key
            ).fetchone()
            if previous:
                if SpeechEvent.model_validate_json(previous[0]) != event:
                    raise SpeechConflict("同一事件标识不能用于不同内容")
                return False
            ended = db.execute(
                "SELECT body FROM speech_events WHERE classroom_id=? AND session_id=?",
                (classroom_id, event.session_id),
            ).fetchall()
            if any(SpeechEvent.model_validate_json(row[0]).event_type == "end" for row in ended):
                raise SpeechConflict("会话已结束，新事件不能修改课堂")
            db.execute("INSERT INTO speech_events VALUES (?, ?, ?, ?)", (*key, event.model_dump_json()))
            if event.segment_id:
                self._apply(db, classroom_id, event)
        return True

    def _apply(self, db: sqlite3.Connection, classroom_id: str, event: SpeechEvent) -> None:
        key = (classroom_id, event.session_id, event.segment_id)
        row = db.execute(
            "SELECT body FROM utterances WHERE classroom_id=? AND session_id=? AND segment_id=?", key
        ).fetchone()
        old = Utterance.model_validate_json(row[0]) if row else None
        if event.event_type not in {"partial", "final", "revision", "withdraw"}:
            return
        if old:
            if event.revision < old.revision:
                return
            if event.revision == old.revision:
                if old.phase != "partial" and event.event_type == "partial":
                    return
                if old.phase == event.event_type:
                    if old.phase == "partial" and event.sequence <= old.sequence:
                        return
                    if old.phase != "partial":
                        if event.text == old.upstream_text:
                            return
                        raise SpeechConflict("同版本定稿内容冲突，需要递增修订号")
                elif old.phase != "partial":
                    raise SpeechConflict("定稿后变更必须递增修订号")
        current = Utterance(
            session_id=event.session_id,
            segment_id=event.segment_id,
            revision=event.revision,
            sequence=event.sequence,
            phase=event.event_type,
            source_kind=event.source_kind,
            start_ms=event.start_ms,
            end_ms=event.end_ms,
            upstream_text=event.text or (old.upstream_text if old else ""),
            source_ref=event.source_ref,
            overlap=event.overlap,
            version=old.version + 1 if old else 1,
            teacher_text=old.teacher_text if old else None,
            student_alias=old.student_alias if old else None,
            question_id=old.question_id if old else None,
        )
        db.execute("INSERT OR REPLACE INTO utterances VALUES (?, ?, ?, ?)", (*key, current.model_dump_json()))
