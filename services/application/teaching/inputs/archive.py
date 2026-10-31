import io
import wave

from ..audio.media import AudioAsset, AudioStore
from ..classroom.storage import StoreError
from .models import InputSession


def pcm_wav(session: InputSession, frames: list[bytes]) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(session.channels)
        output.setsampwidth(2)
        output.setframerate(session.sample_rate)
        for frame in frames:
            output.writeframesraw(frame)
    return buffer.getvalue()


def verify_archive(audio: AudioStore, session: InputSession, frames: list[bytes]) -> AudioAsset:
    asset, path = audio.get(session.classroom_id, session.id)
    expected = b"".join(frames)
    if (
        asset.source != f"{session.input_mode}_{session.processing_mode}"
        or asset.sample_rate != session.sample_rate
        or asset.channels != session.channels
        or asset.duration_ms != session.received_samples * 1000 // session.sample_rate
    ):
        raise StoreError(409, "既有音频元数据与采集会话不匹配，拒绝采用或覆盖")
    try:
        with wave.open(str(path), "rb") as saved:
            matched = (
                saved.getframerate() == session.sample_rate
                and saved.getnchannels() == session.channels
                and saved.getsampwidth() == 2
                and saved.getnframes() == session.received_samples
                and len(expected) == session.received_samples * session.channels * 2
                and saved.readframes(saved.getnframes()) == expected
            )
    except (OSError, wave.Error, EOFError):
        raise StoreError(409, "既有音频无法核对，拒绝采用或覆盖") from None
    if not matched:
        raise StoreError(409, "既有音频样本与已收帧不一致，拒绝采用或覆盖")
    return asset


def archive_or_recover(audio: AudioStore, session: InputSession, frames: list[bytes]) -> AudioAsset:
    try:
        return verify_archive(audio, session, frames)
    except StoreError as error:
        if error.status != 404:
            raise
    try:
        audio.save(
            session.classroom_id, session.id, pcm_wav(session, frames),
            source=f"{session.input_mode}_{session.processing_mode}"
        )
    except StoreError as error:
        if error.status != 409:
            raise
    try:
        return verify_archive(audio, session, frames)
    except StoreError as error:
        if error.status == 404:
            raise StoreError(409, "归档记录存在但音频不可核对，拒绝覆盖") from None
        raise
