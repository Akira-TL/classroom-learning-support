import pytest
from pydantic import TypeAdapter
from test_evidence import Environment
from test_evidence import environment as environment

from teaching.classroom.classrooms import UpdateClassroom
from teaching.deepseek import DeepSeek, GenerationError
from teaching.learning.models import EvidenceRecord, EvidenceReview, GenerationResult, ManualEvidenceRequest
from teaching.models import EvidenceContent

QUOTE = "分成四块就都是四分之一"


def request(key: str = "manual-evidence-01", version: int = 2) -> ManualEvidenceRequest:
    return ManualEvidenceRequest(
        session_id="s-1",
        segment_id="u-1",
        expected_version=version,
        idempotency_key=key,
        content=EvidenceContent(
            quote=QUOTE,
            interpretation="教师判断需核实平均分条件",
            limitation="只来自本次回答",
            follow_up_question="四块的面积是否相等？",
        ),
    )


@pytest.fixture
def no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_cls: type[DeepSeek], _client: object) -> DeepSeek:
        raise AssertionError("人工录入不得请求云端模型")

    monkeypatch.setattr(DeepSeek, "from_environment", classmethod(fail))


def save(environment: Environment, payload: ManualEvidenceRequest) -> GenerationResult:
    response = environment.client.post(f"{environment.url}/manual", content=payload.model_dump_json())
    assert response.status_code == 200
    return GenerationResult.model_validate_json(response.content)


def test_manual_initial_draft_edit_and_retry_preserve_source(environment: Environment, no_model: None) -> None:
    environment.verify()
    result = save(environment, request())
    assert result.task.origin == "teacher_manual"
    assert result.task.manual_content == request().content
    assert result.task.status == "succeeded"
    assert result.evidence.status == "pending"
    assert result.evidence.original.model == "teacher_manual"
    edited = result.evidence.content.model_copy(update={"interpretation": "后续教师修订的解释"})
    response = environment.client.put(
        f"{environment.url}/{result.evidence.id}/review",
        content=EvidenceReview(expected_revision=1, action="confirmed", content=edited).model_dump_json(),
    )
    confirmed = EvidenceRecord.model_validate_json(response.content)
    assert confirmed.status == "confirmed"
    repeated = save(environment, request())
    assert repeated.evidence.id == result.evidence.id
    assert repeated.evidence.content.interpretation == "后续教师修订的解释"
    assert repeated.evidence.original.content.interpretation == "教师判断需核实平均分条件"
    assert (
        environment.client.post(
            f"{environment.url}/generate",
            content=result.task.request.model_dump_json(),
        ).status_code
        == 409
    )
    changed = request().model_copy(update={"content": edited})
    assert (
        environment.client.post(
            f"{environment.url}/manual",
            content=changed.model_dump_json(),
        ).status_code
        == 409
    )


def test_manual_checks_quote_version_verification_and_permissions(environment: Environment, no_model: None) -> None:
    assert (
        environment.client.post(
            f"{environment.url}/manual",
            content=request(version=1).model_dump_json(),
        ).status_code
        == 409
    )
    environment.verify()
    assert (
        environment.client.post(
            f"{environment.url}/manual",
            content=request(version=1).model_dump_json(),
        ).status_code
        == 409
    )
    invalid = request().model_copy(update={"content": request().content.model_copy(update={"quote": "不存在的原话"})})
    assert (
        environment.client.post(
            f"{environment.url}/manual",
            content=invalid.model_dump_json(),
        ).status_code
        == 422
    )
    for name in ("teacher-02", "student-01", "parent-01", "admin-01"):
        environment.client.post("/api/auth/login", json={"username": name, "password": "evidence-test-password"})
        assert (
            environment.client.post(
                f"{environment.url}/manual",
                content=request().model_dump_json(),
            ).status_code
            == 403
        )


def test_manual_still_requires_missing_diagram_context(environment: Environment, no_model: None) -> None:
    environment.verify()
    current = environment.store.get_classroom("teacher-01", environment.cid)
    environment.store.update_classroom(
        "teacher-01",
        environment.cid,
        UpdateClassroom(
            **current.model_dump(exclude={"id", "teacher_id", "revision", "questions"}),
            questions=[current.questions[0].model_copy(update={"diagram_required": True})],
            expected_revision=1,
        ),
    )
    assert (
        environment.client.post(
            f"{environment.url}/manual",
            content=request().model_dump_json(),
        ).status_code
        == 422
    )


def test_correction_invalidates_manual_evidence_without_erasing_original(
    environment: Environment, no_model: None
) -> None:
    environment.verify()
    result = save(environment, request())
    environment.verify(2, "student-02")
    listing = TypeAdapter(list[GenerationResult]).validate_json(environment.client.get(environment.url).content)
    assert listing[0].evidence.id == result.evidence.id
    assert listing[0].task.status == "stale"
    assert listing[0].evidence.status == "stale"
    assert listing[0].evidence.original.content == request().content
    assert save(environment, request()).evidence.status == "stale"


def test_manual_cannot_replace_a_failed_generation_request(
    environment: Environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment.verify()

    def fail(_cls: type[DeepSeek], _client: object) -> DeepSeek:
        raise GenerationError("受控生成失败")

    monkeypatch.setattr(DeepSeek, "from_environment", classmethod(fail))
    result = GenerationResult.model_validate_json(environment.generate(key="manual-evidence-01").content)
    assert result.task.status == "failed"
    assert (
        environment.client.post(
            f"{environment.url}/manual",
            content=request().model_dump_json(),
        ).status_code
        == 409
    )
    saved = save(environment, request("manual-after-failure"))
    assert saved.evidence.status == "pending"
    listing = TypeAdapter(list[GenerationResult]).validate_json(environment.client.get(environment.url).content)
    assert listing[0].task.status == "failed"
    assert listing[0].task.origin == "deepseek"
