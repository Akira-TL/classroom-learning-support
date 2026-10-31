import argparse
import hashlib
import wave
from datetime import date
from pathlib import Path

import httpx
from pydantic import TypeAdapter

from ..audio.media import AudioAsset
from ..audio.models import Utterance
from ..care.tags.models import TagBatch
from ..classroom.auth import DemoLoginRequest
from ..classroom.classrooms import Classroom, CreateClassroom, Question
from .models import Recording
from .plan import STUDENTS, mock_batches, speech_events


def main() -> None:
    parser = argparse.ArgumentParser(description="导入本机录制课堂和学生演示状态")
    parser.add_argument("materials", type=Path)
    parser.add_argument("--date", type=date.fromisoformat, default=date(2026, 10, 31))
    args = parser.parse_args()
    recording = Recording.model_validate_json(args.materials.read_bytes())
    audio_path = Path(recording.audio_path)
    with wave.open(str(audio_path)) as audio:
        if audio.getnframes() * 1000 // audio.getframerate() != recording.duration_ms:
            raise ValueError("播放音频时长与资料不一致")
    if audio_path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("请先转换为20MB以内的PCM WAV")
    key = "recorded-" + hashlib.sha256((recording.model_dump_json() + args.date.isoformat()).encode()).hexdigest()[:24]
    request = CreateClassroom(
        title=recording.title, date=args.date, students=list(STUDENTS),
        objective="用手指理解加法与减法，关注学生表达和课堂状态变化",
        questions=[Question(id="add-one", text="1＋1等于几？", reference_answer="2。再竖起一根手指，共两根。"),
                   Question(id="add-two", text="1＋2等于几？", reference_answer="3。一根与两根合起来，共三根。"),
                   Question(id="subtract", text="5－1等于几？", reference_answer="4。五根手指收起一根，剩四根。")],
        source="用户提供课堂录制与时间记录", authorization="按用户要求用于本机比赛演示",
        idempotency_key=key,
    )
    with httpx.Client(base_url="http://127.0.0.1:8000", trust_env=False, timeout=60) as client:
        client.post("/api/auth/demo-login", content=DemoLoginRequest(role="teacher").model_dump_json(),
                    headers={"Content-Type": "application/json"}).raise_for_status()
        response = client.post("/api/classrooms", content=request.model_dump_json(),
                               headers={"Content-Type": "application/json"})
        response.raise_for_status()
        classroom = Classroom.model_validate_json(response.content)
        prefix = f"/api/classrooms/{classroom.id}"
        for event in speech_events(recording, key):
            response = client.post(f"{prefix}/speech/events", content=event.model_dump_json(),
                                   headers={"Content-Type": "application/json"})
            response.raise_for_status()
        timeline_response = client.get(f"{prefix}/speech/timeline")
        timeline_response.raise_for_status()
        timeline = TypeAdapter(list[Utterance]).validate_json(timeline_response.content)
        if not all(item.audio_available for item in timeline if item.session_id == key):
            response = client.post(f"{prefix}/speech/{key}/audio", content=audio_path.read_bytes(),
                                   headers={"Content-Type": "audio/wav"})
            response.raise_for_status()
            asset = AudioAsset.model_validate_json(response.content)
            assert asset.duration_ms == recording.duration_ms
        for batch in mock_batches(recording, key, args.date):
            response = client.post(f"{prefix}/care/tag-batches", content=batch.model_dump_json(),
                                   headers={"Content-Type": "application/json"})
            response.raise_for_status()
            saved = TagBatch.model_validate_json(response.content)
            assert saved.student_id == batch.student_id
        output = args.materials.parent / "import-result.json"
        output.write_text(classroom.model_dump_json(indent=2), encoding="utf-8")
        print(f"课堂已导入：{classroom.title}；学生3名；转写{len(recording.transcripts)}段")
        print(f"课堂编号：{classroom.id}；音频{recording.duration_ms / 1000:.3f}秒")


if __name__ == "__main__":
    main()
