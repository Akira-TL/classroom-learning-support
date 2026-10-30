import json

import httpx
import pytest
from pydantic import ValidationError

from teaching.deepseek import DeepSeek, GenerationError
from teaching.models import ConfirmedEvidence, VerifiedContext


@pytest.fixture
def context() -> VerifiedContext:
    return VerifiedContext(
        question_id="q-1",
        question_revision=1,
        objective="理解平均分",
        question="四块是否一定各为四分之一？",
        reference_answer="只有平均分才成立",
        utterance_id="u-1",
        utterance_revision=2,
        student_alias="student-01",
        utterance="分成四块就都是四分之一",
        text_confirmed=True,
        identity_confirmed=True,
        question_confirmed=True,
    )


def reply(content: str, finish: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
        },
    )


def evidence_json(quote: str) -> str:
    return json.dumps(
        {
            "quote": quote,
            "interpretation": "需要核实平均分条件",
            "limitation": "单次回答不足以确定稳定掌握",
            "follow_up_question": "四块是否同样大？",
        },
        ensure_ascii=False,
    )


def test_evidence_remains_a_draft_with_exact_source(context: VerifiedContext) -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"] == "Bearer test-secret"
        assert b"test-secret" not in request.content
        return reply(evidence_json(context.utterance))

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        result = DeepSeek(client, "test-secret").analyze(context)
    assert result.status == "pending_teacher_review"
    assert result.context.utterance_revision == 2
    assert result.content.interpretation == "需要核实平均分条件"
    assert "test-secret" not in result.model_dump_json()


@pytest.mark.parametrize(
    "content,finish",
    [
        ("   ", "stop"),
        ("not json", "stop"),
        ("{}", "stop"),
        (evidence_json("未在课堂出现的原话"), "stop"),
        (evidence_json("分成四块就都是四分之一"), "length"),
    ],
)
def test_invalid_output_never_becomes_evidence(context: VerifiedContext, content: str, finish: str) -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _: reply(content, finish))) as client:
        with pytest.raises(GenerationError):
            DeepSeek(client, "test-secret").analyze(context)


@pytest.mark.parametrize("status", [401, 402, 429, 500, 302])
def test_http_failures_do_not_expose_body_or_secret(context: VerifiedContext, status: int) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(status, text="private response test-secret"),
        )
    ) as client:
        with pytest.raises(GenerationError) as captured:
            DeepSeek(client, "test-secret").analyze(context)
    assert str(status) in str(captured.value)
    assert "private" not in str(captured.value)
    assert "test-secret" not in str(captured.value)


def test_timeout_is_safe_to_display(context: VerifiedContext) -> None:
    def transport(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private response test-secret", request=request)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(GenerationError, match="超时") as captured:
            DeepSeek(client, "test-secret").analyze(context)
    assert "test-secret" not in str(captured.value)


def test_unverified_or_missing_diagram_is_rejected(context: VerifiedContext) -> None:
    with pytest.raises(ValidationError):
        VerifiedContext.model_validate(context.model_dump() | {"identity_confirmed": False})
    with pytest.raises(ValidationError):
        VerifiedContext.model_validate(context.model_dump() | {"diagram_required": True})


def test_support_requires_confirmed_evidence_and_remains_draft(context: VerifiedContext) -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _: reply(evidence_json(context.utterance)))) as client:
        evidence = DeepSeek(client, "test-secret").analyze(context)
    with pytest.raises(ValidationError):
        ConfirmedEvidence(draft=evidence, teacher_confirmed=False)
    confirmed = ConfirmedEvidence(draft=evidence, teacher_confirmed=True)
    content = json.dumps(
        {
            "exercises": [
                {
                    "level": level,
                    "question": "平均分成四份，每份是多少？",
                    "answer": "四分之一",
                    "explanation": "每份相等",
                }
                for level in ["concept", "explanation", "transfer"]
            ],
            "classroom_question": "为何必须平均分？",
            "next_lesson": "比较等分与不等分",
            "check_method": "用新的例子解释",
        },
        ensure_ascii=False,
    )
    with httpx.Client(transport=httpx.MockTransport(lambda _: reply(content))) as client:
        result = DeepSeek(client, "test-secret").support(confirmed)
    assert result.status == "pending_teacher_review"
    assert len(result.content.exercises) == 3
    assert result.evidence.draft.context.utterance_id == "u-1"


def test_missing_secret_fails_without_network() -> None:
    with httpx.Client() as client, pytest.raises(GenerationError, match="未配置"):
        DeepSeek(client, "")
