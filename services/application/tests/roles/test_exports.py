from dataclasses import dataclass

import pytest
from pydantic import TypeAdapter
from test_evidence import environment as environment
from test_evidence import model_response as model_response
from test_exercises import ResponseInstaller, output
from test_exercises import control as control
from test_exercises import ready as ready
from test_plans import PlanEnvironment
from test_plans import planning as planning

from teaching.classroom.classrooms import UpdateClassroom
from teaching.exports.models import CreateExport, ExportMetadata
from teaching.plans.models import PlanGenerationResult, PlanRecord
from teaching.reports.models import PublishRequest
from teaching.reports.store import ReportStore


@dataclass
class Exports:
    planning: PlanEnvironment
    plan: PlanRecord

    @property
    def url(self) -> str:
        return f"/api/classrooms/{self.planning.ready.env.cid}/exports"

    def request(self) -> CreateExport:
        return CreateExport(
            plan_id=self.plan.id, expected_plan_revision=self.plan.revision, idempotency_key="export-01"
        )

    def create(self) -> ExportMetadata:
        response = self.planning.ready.env.client.post(self.url, content=self.request().model_dump_json())
        assert response.status_code == 200
        return ExportMetadata.model_validate_json(response.content)

    def login(self, name: str) -> None:
        assert (
            self.planning.ready.env.client.post(
                "/api/auth/login",
                json={
                    "username": name,
                    "password": "evidence-test-password",
                },
            ).status_code
            == 200
        )


@pytest.fixture
def exports(planning: PlanEnvironment, control: ResponseInstaller) -> Exports:
    control(lambda request: output())
    plan = PlanGenerationResult.model_validate_json(planning.generate().content).plan
    confirmed = PlanRecord.model_validate_json(planning.complete(plan).content)
    return Exports(planning, confirmed)


def test_export_is_self_contained_escaped_and_idempotent(exports: Exports) -> None:
    env = exports.planning.ready.env
    classroom = env.store.get_classroom("teacher-01", env.cid)
    env.store.update_classroom(
        "teacher-01",
        env.cid,
        UpdateClassroom(
            **classroom.model_dump(exclude={"id", "teacher_id", "revision"}) | {"title": '<script>alert("x")</script>'},
            expected_revision=classroom.revision,
        ),
    )
    result = exports.create()
    assert exports.create().id == result.id
    changed = exports.request().model_copy(update={"expected_plan_revision": 3})
    assert env.client.post(exports.url, content=changed.model_dump_json()).status_code == 409
    response = env.client.get(f"/api/exports/{result.id}/download")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text
    assert 'src="http' not in response.text
    assert "教师确认需比较面积相等条件" in response.text
    assert "先让学生独立比较面积" in response.text
    assert "已下载副本不能远程收回" in response.text
    assert f"http://127.0.0.1:3000/api/exports/{result.id}/status" in response.text
    assert (env.store.path.parent / "exports" / f"{result.id}.html").is_file()


def test_download_permission_and_public_status_minimization(exports: Exports) -> None:
    result = exports.create()
    client = exports.planning.ready.env.client
    exports.login("teacher-02")
    assert client.get(f"/api/exports/{result.id}/download").status_code == 403
    assert client.get(exports.url).status_code == 403
    exports.login("student-01")
    assert client.get(f"/api/exports/{result.id}/download").status_code == 403
    client.post("/api/auth/logout")
    response = client.get(f"/api/exports/{result.id}/status")
    assert response.status_code == 200
    assert set(response.json()) == {"id", "revision", "created_at", "status"}
    assert "student" not in response.text
    assert client.get("/api/exports/unknown/status").status_code == 404


def test_revision_and_revocation_stop_old_downloads(exports: Exports) -> None:
    result = exports.create()
    client = exports.planning.ready.env.client
    assert client.post(f"{exports.url}/{result.id}/revoke", json={"expected_revision": 1}).status_code == 200
    assert client.get(f"/api/exports/{result.id}/download").status_code == 410
    assert (
        ExportMetadata.model_validate_json(client.get(f"/api/exports/{result.id}/status").content).status == "revoked"
    )
    other = exports.request().model_copy(update={"idempotency_key": "export-02"})
    second = ExportMetadata.model_validate_json(client.post(exports.url, content=other.model_dump_json()).content)
    exports.planning.ready.env.verify(2, "student-02")
    assert client.get(f"/api/exports/{second.id}/download").status_code == 410
    assert ExportMetadata.model_validate_json(client.get(f"/api/exports/{second.id}/status").content).status == "stale"


def test_unconfirmed_plan_rejected_and_parent_revision_rechecked(exports: Exports) -> None:
    env = exports.planning.ready.env
    parent = ReportStore(env.store).publish(
        env.cid,
        "teacher-01",
        PublishRequest(
            evidence_id=exports.plan.evidence_id,
            expected_evidence_revision=exports.plan.evidence_revision,
            student_id="student-01",
            summary="已核验的摘要",
            home_activity="请解释平均分",
            idempotency_key="parent-01",
        ),
    )
    request = exports.request().model_copy(update={"parent_report_id": parent.id, "expected_parent_revision": 1})
    result = ExportMetadata.model_validate_json(env.client.post(exports.url, content=request.model_dump_json()).content)
    assert "已核验的摘要" in env.client.get(f"/api/exports/{result.id}/download").text
    env.client.post(f"/api/classrooms/{env.cid}/parent-reports/{parent.id}/revoke", json={"expected_revision": 1})
    assert env.client.get(f"/api/exports/{result.id}/download").status_code == 410
    env.client.put(
        f"{exports.planning.url}/{exports.plan.id}/review", json={"expected_revision": 2, "action": "rejected"}
    )
    invalid = exports.request().model_copy(update={"idempotency_key": "export-new"})
    assert env.client.post(exports.url, content=invalid.model_dump_json()).status_code == 409


def test_export_write_failure_has_no_entry_or_partial_file(exports: Exports, monkeypatch: pytest.MonkeyPatch) -> None:
    env = exports.planning.ready.env

    def fail(metadata: ExportMetadata, source: object) -> str:
        raise OSError("simulated file failure")

    monkeypatch.setattr("teaching.exports.store.render_report", fail)
    with pytest.raises(OSError, match="simulated file failure"):
        exports.create()
    assert TypeAdapter(list[ExportMetadata]).validate_json(env.client.get(exports.url).content) == []
    directory = env.store.path.parent / "exports"
    assert list(directory.iterdir()) == []
