import base64
import binascii
import sqlite3
from pathlib import Path
from uuid import uuid4

from ..audio.media import AudioStore
from ..classroom.storage import SQLiteStore, StoreError
from .archive import archive_or_recover
from .models import CreateInput, FinishInput, InputFrame, InputSession, InputState


class InputStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self.audio = AudioStore(store.path)
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS input_sessions (
                    id TEXT PRIMARY KEY, classroom_id TEXT NOT NULL, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS input_frames (
                    classroom_id TEXT NOT NULL, session_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    start_sample INTEGER NOT NULL, frame_count INTEGER NOT NULL, body BLOB NOT NULL,
                    PRIMARY KEY(classroom_id,session_id,sequence)
                );
            """)

    def owner(self, db: sqlite3.Connection, cid: str, teacher: str) -> None:
        row = db.execute("SELECT teacher_id FROM classrooms WHERE id=?", (cid,)).fetchone()
        if not row:
            raise StoreError(410, "课堂已删除或不可用，不能接收音频")
        if row[0] != teacher:
            raise StoreError(403, "无权访问此课堂音频")

    def _session(self, db: sqlite3.Connection, cid: str, sid: str) -> InputSession:
        row = db.execute("SELECT body FROM input_sessions WHERE id=? AND classroom_id=?", (sid, cid)).fetchone()
        if not row:
            raise StoreError(404, "采集会话不存在")
        return InputSession.model_validate_json(row[0])

    def _save(self, db: sqlite3.Connection, session: InputSession) -> None:
        db.execute("UPDATE input_sessions SET body=? WHERE id=?", (session.model_dump_json(), session.id))

    def create(self, cid: str, teacher: str, request: CreateInput) -> InputSession:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owner(db, cid, teacher)
            session = InputSession(**request.model_dump(), id=uuid4().hex, classroom_id=cid)
            db.execute("INSERT INTO input_sessions VALUES (?, ?, ?)", (session.id, cid, session.model_dump_json()))
        return session

    def list(self, cid: str, teacher: str) -> list[InputSession]:
        with self.store.connection() as db:
            self.owner(db, cid, teacher)
            rows = db.execute("SELECT body FROM input_sessions WHERE classroom_id=? ORDER BY rowid", (cid,)).fetchall()
        return [InputSession.model_validate_json(row[0]) for row in rows]

    def get(self, cid: str, teacher: str, sid: str) -> InputSession:
        with self.store.connection() as db:
            self.owner(db, cid, teacher)
            return self._session(db, cid, sid)

    def frame(self, cid: str, teacher: str, sid: str, request: InputFrame) -> InputSession:
        try:
            raw = base64.b64decode(request.pcm_base64, validate=True)
        except (binascii.Error, ValueError):
            raise StoreError(422, "PCM帧必须是严格Base64编码") from None
        if len(raw) != request.frame_count * 2 or len(raw) > 65536:
            raise StoreError(422, "PCM字节数须等于样本数乘2，且每帧不超过64KB")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owner(db, cid, teacher)
            session = self._session(db, cid, sid)
            row = db.execute(
                "SELECT start_sample,frame_count,body FROM input_frames WHERE classroom_id=? "
                "AND session_id=? AND sequence=?",
                (cid, sid, request.sequence),
            ).fetchone()
            if row:
                if (row[0], row[1], row[2]) != (request.start_sample, request.frame_count, raw):
                    raise StoreError(409, "相同帧序号不能发送不同音频内容")
                return session
            if session.status != "recording":
                raise StoreError(409, "会话不在接收状态，不能继续发送新帧")
            if request.sequence != session.expected_sequence or request.start_sample != session.received_samples:
                raise StoreError(
                    409, f"缺帧或游标不连续，应发送序号{session.expected_sequence}，起始样本{session.received_samples}"
                )
            samples = session.received_samples + request.frame_count
            if samples > session.sample_rate * 600 or samples * 2 > AudioStore.max_bytes - 44:
                raise StoreError(413, "音频累计超过10分钟或20MB限制，当前帧未接收")
            db.execute(
                "INSERT INTO input_frames VALUES (?, ?, ?, ?, ?, ?)",
                (cid, sid, request.sequence, request.start_sample, request.frame_count, raw),
            )
            session = session.model_copy(
                update={"received_samples": samples, "expected_sequence": session.expected_sequence + 1}
            )
            self._save(db, session)
        return session

    def state(self, cid: str, teacher: str, sid: str, request: InputState) -> InputSession:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owner(db, cid, teacher)
            session = self._session(db, cid, sid)
            if session.input_mode != "file_stream":
                raise StoreError(409, "麦克风入口不支持暂停，请停止后创建新会话")
            if session.status not in {"recording", "paused"}:
                raise StoreError(409, "当前会话不能暂停或继续")
            session = session.model_copy(update={"status": "paused" if request.action == "pause" else "recording"})
            self._save(db, session)
        return session

    def finish(self, cid: str, teacher: str, sid: str, request: FinishInput) -> InputSession:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owner(db, cid, teacher)
            session = self._session(db, cid, sid)
            if session.status in {"ended", "failed", "finishing"}:
                return session
            if request.interrupted or session.received_samples == 0:
                session = session.model_copy(
                    update={"status": "failed", "error": "音频接收中断或没有样本，未作完整归档"}
                )
                self._save(db, session)
                return session
            session = session.model_copy(update={"status": "finishing"})
            self._save(db, session)
            rows = db.execute(
                "SELECT body FROM input_frames WHERE classroom_id=? AND session_id=? ORDER BY sequence", (cid, sid)
            ).fetchall()
            frames = [row[0] for row in rows]
        asset = None
        failure: str | None = None
        try:
            asset = archive_or_recover(self.audio, session, frames)
        except StoreError as error:
            if error.status == 410:
                raise
            failure = "音频归档失败，已收帧保留，未声明识别完成"
        except OSError:
            failure = "本机音频写入失败，已收帧保留，未声明识别完成"
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owner(db, cid, teacher)
            current = self._session(db, cid, sid)
            if current.status == "ended":
                return current
            session = current.model_copy(
                update={
                    "status": "failed" if failure else "ended",
                    "audio_asset": asset,
                    "error": failure,
                }
            )
            self._save(db, session)
        return session

    def recover(self, cid: str, teacher: str, sid: str) -> InputSession:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owner(db, cid, teacher)
            session = self._session(db, cid, sid)
            if session.status != "finishing":
                raise StoreError(409, "只有归档进行中状态可手动恢复")
            rows = db.execute(
                "SELECT body FROM input_frames WHERE classroom_id=? AND session_id=? ORDER BY sequence", (cid, sid)
            ).fetchall()
            frames = [row[0] for row in rows]
        try:
            asset = archive_or_recover(self.audio, session, frames)
        except (StoreError, OSError) as error:
            with self.store.connection() as db:
                self.owner(db, cid, teacher)
            if isinstance(error, OSError):
                raise StoreError(503, "本机归档仍不可写，请修复后手动恢复") from None
            raise
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.owner(db, cid, teacher)
            current = self._session(db, cid, sid)
            if current.status == "ended":
                if current.audio_asset != asset:
                    raise StoreError(409, "恢复结果与当前归档不一致")
                return current
            if current.status != "finishing":
                raise StoreError(409, "会话状态已变化，不能恢复")
            current = current.model_copy(update={"status": "ended", "audio_asset": asset, "error": None})
            self._save(db, current)
        return current

    def audio_path(self, cid: str, teacher: str, sid: str) -> Path:
        session = self.get(cid, teacher, sid)
        if session.status != "ended" or session.audio_asset is None:
            raise StoreError(404, "采集会话没有可播放的完整归档")
        return self.audio.get(cid, sid)[1]
