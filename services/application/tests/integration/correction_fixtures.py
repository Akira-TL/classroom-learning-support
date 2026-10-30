from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from teaching.api import create_app
from teaching.audio.models import ReviewRequest, SpeechEvent
from teaching.audio.store import SpeechStore
from teaching.classroom.auth import AuthSettings
from teaching.classroom.classrooms import CreateClassroom, Question
from teaching.classroom.storage import SQLiteStore
from teaching.deepseek import ChatReply, ChatRequest, Choice, DeepSeek, ReplyMessage
from teaching.exercises.models import ExerciseGenerationResult, ExerciseRecord
from teaching.learning.models import EvidenceRecord, GenerationResult
from teaching.models import EvidenceContent, Exercise, SupportContent
from teaching.plans.models import PlanGenerationResult, PlanRecord
from teaching.prompts import EVIDENCE_PROMPT
from teaching.reports.models import ReportView
from teaching.students.models import ReportView as StudentView

PASSWORD = "correction-test-password"
QUOTE = "分成四块就是四分之一"


@dataclass
class Chain:
    evidence: EvidenceRecord
    exercise: ExerciseRecord
    plan: PlanRecord
    student: StudentView
    parent: ReportView | None


@dataclass
class Environment:
    client: TestClient
    store: SQLiteStore
    speech: SpeechStore
    cid: str

    @property
    def base(self) -> str:
        return f"/api/classrooms/{self.cid}"

    def chain(self, segment: str, student: str) -> Chain:
        self.speech.receive(
            self.cid,
            SpeechEvent(
                session_id="s-1",
                event_id=segment,
                sequence=1,
                segment_id=segment,
                event_type="final",
                source_kind="synthetic",
                text=QUOTE,
            ),
        )
        self.speech.review(
            self.cid,
            "s-1",
            segment,
            "teacher-01",
            ReviewRequest(
                expected_version=1,
                student_alias=student,
                question_id="q-1",
                text_review="confirmed",
                identity_review="confirmed",
                question_review="confirmed",
            ),
        )
        generated = self.client.post(
            f"{self.base}/evidence/generate",
            json={
                "session_id": "s-1",
                "segment_id": segment,
                "expected_version": 2,
                "idempotency_key": f"evidence-{segment}",
            },
        )
        result = GenerationResult.model_validate_json(generated.content)
        response = self.client.put(
            f"{self.base}/evidence/{result.evidence.id}/review",
            json={
                "expected_revision": 1,
                "action": "confirmed",
            },
        )
        evidence = EvidenceRecord.model_validate_json(response.content)
        response = self.client.post(
            f"{self.base}/exercises/generate",
            json={
                "evidence_id": evidence.id,
                "expected_evidence_revision": 2,
                "idempotency_key": f"exercise-{segment}",
            },
        )
        exercise = ExerciseGenerationResult.model_validate_json(response.content).exercise_set
        response = self.client.put(
            f"{self.base}/exercises/{exercise.id}/review",
            json={
                "expected_revision": 1,
                "action": "confirmed",
                "exercises": [
                    item.model_copy(update={"answer": "教师保留的 1/4"}).model_dump() for item in exercise.exercises
                ],
            },
        )
        exercise = ExerciseRecord.model_validate_json(response.content)
        response = self.client.put(
            f"{self.base}/exercises/{exercise.id}/adoption",
            json={
                "expected_revision": 2,
                "adopted": True,
            },
        )
        exercise = ExerciseRecord.model_validate_json(response.content)
        response = self.client.post(
            f"{self.base}/plans/generate",
            json={
                "evidence_id": evidence.id,
                "expected_evidence_revision": 2,
                "idempotency_key": f"plan-{segment}",
            },
        )
        plan = PlanGenerationResult.model_validate_json(response.content).plan
        content = plan.content.model_copy(
            update={
                "preparation": "先独立思考",
                "alternative": "给出反例",
                "keep_content": "保留平均分定义",
            }
        )
        response = self.client.put(
            f"{self.base}/plans/{plan.id}/review",
            json={
                "expected_revision": 1,
                "action": "confirmed",
                "content": content.model_dump(),
            },
        )
        plan = PlanRecord.model_validate_json(response.content)
        response = self.client.put(
            f"{self.base}/plans/{plan.id}/adoption",
            json={
                "expected_revision": 2,
                "adopted": True,
                "observation": "人工观察应保留",
            },
        )
        plan = PlanRecord.model_validate_json(response.content)
        response = self.client.post(
            f"{self.base}/student-reports",
            json={
                "exercise_set_id": exercise.id,
                "expected_exercise_revision": exercise.revision,
                "student_id": student,
                "feedback": "需要比较大小",
                "idempotency_key": f"student-{segment}",
            },
        )
        student_report = StudentView.model_validate_json(response.content)
        parent = None
        if student == "student-01":
            response = self.client.post(
                f"{self.base}/parent-reports",
                json={
                    "evidence_id": evidence.id,
                    "expected_evidence_revision": 2,
                    "student_id": student,
                    "summary": "家长摘要",
                    "home_activity": "平均分一张纸",
                    "idempotency_key": f"parent-{segment}",
                },
            )
            parent = ReportView.model_validate_json(response.content)
        return Chain(evidence, exercise, plan, student_report, parent)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Environment]:
    def transport(request: httpx.Request) -> httpx.Response:
        prompt = ChatRequest.model_validate_json(request.content).messages[0].content
        if prompt == EVIDENCE_PROMPT:
            output = EvidenceContent(
                quote=QUOTE, interpretation="需核实平均分", limitation="仅本次回答", follow_up_question="一样大吗？"
            )
        else:
            output = SupportContent(
                exercises=[
                    Exercise(level=level, question="平均分成四份每份是多少？", answer="1/4", explanation="四份相等")
                    for level in ("concept", "explanation", "transfer")
                ],
                classroom_question="平均分是什么意思？",
                next_lesson="比较等分",
                check_method="用反例解释",
            )
        reply = ChatReply(
            choices=[Choice(message=ReplyMessage(content=output.model_dump_json()), finish_reason="stop")]
        )
        return httpx.Response(200, content=reply.model_dump_json())

    database = tmp_path / "corrections.sqlite3"
    app = create_app(database, AuthSettings(demo_password=SecretStr(PASSWORD)))
    speech = SpeechStore(database)
    classroom = app.state.store.create_classroom(
        "teacher-01",
        CreateClassroom(
            title="分数",
            date=date(2026, 10, 31),
            objective="平均分",
            students=["student-01", "student-02"],
            questions=[Question(id="q-1", text="四块就是四分之一吗？", reference_answer="需要平均分")],
            source="合成课堂",
            authorization="仅测试",
            idempotency_key="correction-classroom",
        ),
    )
    with httpx.Client(transport=httpx.MockTransport(transport)) as model:
        monkeypatch.setattr(
            DeepSeek, "from_environment", classmethod(lambda cls, unused: DeepSeek(model, "test-secret"))
        )
        with TestClient(app, headers={"Content-Type": "application/json"}) as client:
            assert (
                client.post("/api/auth/login", json={"username": "teacher-01", "password": PASSWORD}).status_code == 200
            )
            yield Environment(client, app.state.store, speech, classroom.id)
