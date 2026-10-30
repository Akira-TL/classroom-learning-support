"""授权会话的本地 WAV 归档；不生成或伪造语音识别结果。"""

import io
import sqlite3
import wave
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from ..classroom.storage import StoreError
from ..models import StrictModel


class AudioAsset(StrictModel):
    id: str
    session_id: str
    duration_ms: int
    channels: int
    sample_rate: int
    source: str = "teacher_uploaded_audio"


class AudioStore:
    max_bytes = 20 * 1024 * 1024

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.root = database_path.parent / "audio"
        self.root.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(database_path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS audio_assets "
                "(classroom_id TEXT, session_id TEXT, asset_id TEXT UNIQUE, body TEXT, "
                "PRIMARY KEY(classroom_id, session_id))"
            )

    def save(
        self, classroom_id: str, session_id: str, content: bytes, *, source: str = "teacher_uploaded_audio"
    ) -> AudioAsset:
        if not content or len(content) > self.max_bytes:
            raise StoreError(413, "音频为空或超过20MB")
        try:
            with wave.open(io.BytesIO(content), "rb") as audio:
                channels = audio.getnchannels()
                rate = audio.getframerate()
                duration = audio.getnframes() * 1000 // rate
                if channels not in {1, 2} or not 8000 <= rate <= 48000 or not 0 < duration <= 600000:
                    raise StoreError(422, "只支持10分钟以内、8—48kHz的单声道或双声道PCM WAV")
                expected = audio.getnframes() * channels * audio.getsampwidth()
                if len(audio.readframes(audio.getnframes())) != expected:
                    raise StoreError(422, "音频数据截断，无法归档")
        except (wave.Error, EOFError, ZeroDivisionError):
            raise StoreError(422, "音频不是有效的PCM WAV") from None
        asset = AudioAsset(
            id=uuid4().hex,
            session_id=session_id,
            duration_ms=duration,
            channels=channels,
            sample_rate=rate,
            source=source,
        )
        path = self.root / f"{asset.id}.wav"
        with closing(sqlite3.connect(self.database_path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM classrooms WHERE id=?", (classroom_id,)).fetchone():
                raise StoreError(410, "课堂已删除，音频未归档")
            if db.execute(
                "SELECT 1 FROM audio_assets WHERE classroom_id=? AND session_id=?", (classroom_id, session_id)
            ).fetchone():
                raise StoreError(409, "会话已归档原音频，不允许覆盖；请创建新会话")
            try:
                path.write_bytes(content)
                db.execute(
                    "INSERT INTO audio_assets VALUES (?, ?, ?, ?)",
                    (classroom_id, session_id, asset.id, asset.model_dump_json()),
                )
                db.commit()
            except BaseException:
                path.unlink(missing_ok=True)
                raise
        return asset

    def get(self, classroom_id: str, session_id: str) -> tuple[AudioAsset, Path]:
        with closing(sqlite3.connect(self.database_path, timeout=10)) as db:
            row = db.execute(
                "SELECT body FROM audio_assets WHERE classroom_id=? AND session_id=?", (classroom_id, session_id)
            ).fetchone()
        if not row:
            raise StoreError(404, "当前会话没有可用原音频，模拟事件本身不包含音轨")
        asset = AudioAsset.model_validate_json(row[0])
        path = self.root / f"{asset.id}.wav"
        if not path.is_file():
            raise StoreError(404, "已归档音频当前不可用")
        return asset, path
