from dataclasses import dataclass

import httpx
import pytest
from pydantic import TypeAdapter
from test_evidence import Environment
from test_evidence import environment as environment
from test_evidence import model_response as model_response

from teaching.learning.models import EvidenceRecord, EvidenceReview, GenerationResult
from teaching.reports.models import (
    ParentQuestion,
    PreviewRequest,
    PublishRequest,
    QuestionRequest,
    ReportPreview,
    ReportView,
    ResolveQuestion,
    RevokeRequest,
)

PASSWORD = "evidence-test-password"


@dataclass
class ReportsEnvironment:
    base: Environment
    request: PublishRequest
    evidence: EvidenceRecord

    @property
    def url(self) -> str:
        return f"/api/classrooms/{self.base.cid}/parent-reports"

    def login(self, username: str) -> None:
        assert (
            self.base.client.post(
                "/api/auth/login",
                json={"username": username, "password": PASSWORD},
            ).status_code
            == 200
        )

    def publish(self) -> ReportView:
        response = self.base.client.post(self.url, content=self.request.model_dump_json())
        assert response.status_code == 200
        return ReportView.model_validate_json(response.content)


@pytest.fixture
def reports(environment: Environment, model_response: list[httpx.Request]) -> ReportsEnvironment:
    environment.verify()
    result = GenerationResult.model_validate_json(environment.generate().content)
    review = EvidenceReview(expected_revision=1, action="confirmed")
    response = environment.client.put(
        f"{environment.url}/{result.evidence.id}/review",
        content=review.model_dump_json(),
    )
    evidence = EvidenceRecord.model_validate_json(response.content)
    request = PublishRequest(
        evidence_id=evidence.id,
        expected_evidence_revision=2,
        student_id="student-01",
        summary="本次回答需要继续核实平均分条件",
        home_activity="共同把一张纸平均分成四份",
        idempotency_key="publish-parent-01",
    )
    return ReportsEnvironment(environment, request, evidence)


def test_preview_publish_and_parent_isolation(reports: ReportsEnvironment) -> None:
    client = reports.base.client
    preview = PreviewRequest.model_validate(reports.request.model_dump(exclude={"idempotency_key"}))
    response = client.post(f"{reports.url}/preview", content=preview.model_dump_json())
    assert response.status_code == 200
    assert ReportPreview.model_validate_json(response.content).parent_id == "parent-01"
    report = reports.publish()
    reports.login("parent-01")
    response = client.get(f"/api/parent-reports/{report.id}")
    assert ReportView.model_validate_json(response.content).summary == reports.request.summary
    assert "upstream_text" not in response.text
    assert "original" not in response.text
    for username in ("student-01", "student-02", "admin-01", "teacher-02"):
        reports.login(username)
        assert client.get(f"/api/parent-reports/{report.id}").status_code == 403
        assert client.get(reports.url).status_code == 403


def test_idempotency_and_evidence_recipient_must_match(reports: ReportsEnvironment) -> None:
    first = reports.publish()
    assert reports.publish().id == first.id
    changed = reports.request.model_copy(update={"summary": "不同内容"})
    assert reports.base.client.post(reports.url, content=changed.model_dump_json()).status_code == 409
    changed = reports.request.model_copy(update={"student_id": "student-02", "idempotency_key": "foreign-student"})
    assert reports.base.client.post(reports.url, content=changed.model_dump_json()).status_code == 422
    listing = TypeAdapter(list[ReportView]).validate_json(reports.base.client.get(reports.url).content)
    assert len(listing) == 1


def test_evidence_change_after_preview_prevents_publish(reports: ReportsEnvironment) -> None:
    client = reports.base.client
    preview = PreviewRequest.model_validate(reports.request.model_dump(exclude={"idempotency_key"}))
    assert client.post(f"{reports.url}/preview", content=preview.model_dump_json()).status_code == 200
    request = EvidenceReview(expected_revision=2, action="rejected")
    assert (
        client.put(
            f"{reports.base.url}/{reports.evidence.id}/review",
            content=request.model_dump_json(),
        ).status_code
        == 200
    )
    assert client.post(reports.url, content=reports.request.model_dump_json()).status_code == 409
    assert TypeAdapter(list[ReportView]).validate_json(client.get(reports.url).content) == []


def test_no_parent_binding_blocks_publication(reports: ReportsEnvironment) -> None:
    reports.base.verify(2, "student-02")
    result = GenerationResult.model_validate_json(reports.base.generate("generate-student-02", 3).content)
    request = EvidenceReview(expected_revision=1, action="confirmed")
    response = reports.base.client.put(
        f"{reports.base.url}/{result.evidence.id}/review",
        content=request.model_dump_json(),
    )
    assert response.status_code == 200
    changed = reports.request.model_copy(
        update={
            "evidence_id": result.evidence.id,
            "student_id": "student-02",
            "idempotency_key": "no-parent-binding",
        }
    )
    response = reports.base.client.post(reports.url, content=changed.model_dump_json())
    assert response.status_code == 409
    assert "家长绑定" in response.text


@pytest.mark.parametrize("change", ["revoke", "identity"])
def test_old_report_and_new_questions_blocked_immediately(reports: ReportsEnvironment, change: str) -> None:
    report = reports.publish()
    if change == "revoke":
        response = reports.base.client.post(
            f"{reports.url}/{report.id}/revoke",
            content=RevokeRequest(expected_revision=1).model_dump_json(),
        )
        assert ReportView.model_validate_json(response.content).status == "revoked"
    else:
        reports.base.verify(2, "student-02")
    reports.login("parent-01")
    response = reports.base.client.get(f"/api/parent-reports/{report.id}")
    assert response.status_code == 410
    assert reports.request.summary not in response.text
    assert reports.request.home_activity not in response.text
    question = QuestionRequest(text="我想确认这条反馈", idempotency_key="ask-after-change")
    assert (
        reports.base.client.post(
            f"/api/parent-reports/{report.id}/questions",
            content=question.model_dump_json(),
        ).status_code
        == 410
    )
    reports.login("teacher-01")
    metadata = ReportView.model_validate_json(reports.base.client.get(f"/api/parent-reports/{report.id}").content)
    assert metadata.summary is None
    assert metadata.home_activity is None


def test_parent_questions_are_idempotent_and_teacher_can_resolve_after_revoke(reports: ReportsEnvironment) -> None:
    report = reports.publish()
    reports.login("parent-01")
    request = QuestionRequest(text="在家应该怎样检查是否平均分？", idempotency_key="ask-parent-01")
    url = f"/api/parent-reports/{report.id}/questions"
    response = reports.base.client.post(url, content=request.model_dump_json())
    assert response.status_code == 200
    question = ParentQuestion.model_validate_json(response.content)
    duplicate = reports.base.client.post(url, content=request.model_dump_json())
    assert ParentQuestion.model_validate_json(duplicate.content).id == question.id
    changed = request.model_copy(update={"text": "另一条问题"})
    assert reports.base.client.post(url, content=changed.model_dump_json()).status_code == 409
    reports.login("teacher-01")
    assert (
        reports.base.client.post(
            f"{reports.url}/{report.id}/revoke",
            content=RevokeRequest(expected_revision=1).model_dump_json(),
        ).status_code
        == 200
    )
    listing_url = f"/api/classrooms/{reports.base.cid}/parent-report-questions"
    listing = TypeAdapter(list[ParentQuestion]).validate_json(reports.base.client.get(listing_url).content)
    assert [item.id for item in listing] == [question.id]
    resolve = ResolveQuestion(expected_revision=1, status="answered", response="请比较每份大小是否相同")
    response = reports.base.client.put(f"{listing_url}/{question.id}", content=resolve.model_dump_json())
    assert response.status_code == 200
    resolved = ParentQuestion.model_validate_json(response.content)
    assert resolved.status == "answered"
    assert resolved.revision == 2
    assert (
        reports.base.client.put(
            f"{listing_url}/{question.id}",
            content=resolve.model_dump_json(),
        ).status_code
        == 409
    )
