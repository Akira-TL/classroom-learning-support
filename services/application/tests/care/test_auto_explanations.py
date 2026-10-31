import json

import httpx
import pytest
from test_evidence import Environment
from test_evidence import environment as environment
from test_tags import batch, periods

from teaching.deepseek import DeepSeek


def install_model(monkeypatch: pytest.MonkeyPatch, calls: list[httpx.Request], callback=None):
    def respond(request: httpx.Request):
        calls.append(request)
        if callback:
            callback()
        result = {"change_explanation": "所提供标签本周次数较多，时长缺失，无法判断发生率变化",
                  "followup_questions": ["这两次采集条件是否一致？"],
                  "summary": "根据提供者的标签了解课堂记录", "followup": "向本人了解当时感受并复核采集条件"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(result)},
                                                     "finish_reason": "stop"}]})

    model = DeepSeek(httpx.Client(transport=httpx.MockTransport(respond)), "synthetic-test-model-key")
    monkeypatch.setattr(DeepSeek, "from_environment", classmethod(lambda cls, client: model))


def test_automatic_generation_cache_and_source_revision_refresh(environment: Environment, monkeypatch):
    calls = []
    install_model(monkeypatch, calls)
    url = f"/api/classrooms/{environment.cid}/care/tag-batches"
    imported = environment.client.post(url, json=batch()).json()
    endpoint = f"/api/classrooms/{environment.cid}/care/explanations"
    request = {"comparison": periods(), "perspective": "head_teacher"}
    generated = environment.client.post(endpoint, json=request)
    assert generated.status_code == 200 and generated.json()["status"] == "generated"
    assert len(calls) == 1
    assert environment.client.post(endpoint, json=request).json()["id"] == generated.json()["id"]
    assert len(calls) == 1
    assert environment.client.put(f"{url}/{imported['id']}", json=batch(count=8) | {
        "expected_revision": 1, "source_version": "v2"}).status_code == 200
    refreshed = environment.client.post(endpoint, json=request).json()
    assert refreshed["source_fingerprint"] != generated.json()["source_fingerprint"]
    assert len(calls) == 2
    prompt = json.loads(calls[0].content)["messages"][0]["content"]
    assert "不从咳嗽诊断感冒" in prompt and "head_teacher" in prompt
    assert environment.client.post(f"/api/classrooms/{environment.cid}/care/reports", json={}).status_code == 404


def test_recipient_binding_and_perspective_are_enforced(environment: Environment, monkeypatch):
    calls = []
    install_model(monkeypatch, calls)
    imported = environment.client.post(f"/api/classrooms/{environment.cid}/care/tag-batches", json=batch())
    assert imported.status_code == 200
    for username, perspective in (("parent-01", "parent"), ("student-01", "student")):
        environment.client.post("/api/auth/login", json={"username": username, "password": "evidence-test-password"})
        request = {"comparison": periods(), "perspective": perspective}
        response = environment.client.post("/api/care/me/explanations", json=request)
        assert response.status_code == 200
        assert "comparison" not in response.json() and "teacher_id" not in response.json()
        assert environment.client.post("/api/care/me/explanations", json=request | {
            "perspective": "teacher"}).status_code == 403
        assert environment.client.post("/api/care/me/explanations", json=request | {
            "comparison": periods() | {"student_id": "student-02"}}).status_code == 403


def test_demo_report_keeps_counts_without_source_metadata(environment: Environment, monkeypatch):
    calls = []
    install_model(monkeypatch, calls)
    payload = batch(count=5) | {"data_origin": "demonstration", "source_description": "内部制作说明"}
    imported = environment.client.post(f"/api/classrooms/{environment.cid}/care/tag-batches", json=payload)
    assert imported.status_code == 200
    generated = environment.client.post(f"/api/classrooms/{environment.cid}/care/explanations", json={
        "comparison": periods(), "perspective": "teacher"})
    assert generated.status_code == 200
    content = json.loads(calls[0].content)["messages"][1]["content"]
    assert "内部制作说明" not in content and "source_description" not in content and "identity_confirmed" not in content
    metrics = json.loads(content)["metrics"]
    cough = next(item for item in metrics if item["label"] == "cough")
    assert cough["current_count"] == 5 and cough["baseline_count"] is None


def test_changed_source_during_generation_is_not_saved_as_current(environment: Environment, monkeypatch):
    url = f"/api/classrooms/{environment.cid}/care/tag-batches"
    imported = environment.client.post(url, json=batch()).json()

    def replace_source():
        assert environment.client.put(f"{url}/{imported['id']}", json=batch(count=9) | {
            "expected_revision": 1, "source_version": "v2"}).status_code == 200

    calls = []
    install_model(monkeypatch, calls, replace_source)
    response = environment.client.post(f"/api/classrooms/{environment.cid}/care/explanations", json={
        "comparison": periods(), "perspective": "teacher"})
    assert response.status_code == 409
    with environment.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM care_explanations").fetchone()[0] == 0


def test_deleting_source_classroom_purges_cross_classroom_explanation_cache(environment: Environment, monkeypatch):
    from teaching.classroom.classrooms import CreateClassroom
    from teaching.deletion.database import clear_database

    existing = environment.store.get_classroom("teacher-01", environment.cid)
    other = environment.store.create_classroom("teacher-01", CreateClassroom.model_validate(
        existing.model_dump(exclude={"id", "teacher_id", "revision"}) | {"idempotency_key": "other-source-classroom"}))
    assert environment.client.post(f"/api/classrooms/{other.id}/care/tag-batches", json=batch()).status_code == 200
    install_model(monkeypatch, [])
    response = environment.client.post(f"/api/classrooms/{environment.cid}/care/explanations", json={
        "comparison": periods(), "perspective": "teacher"})
    assert response.status_code == 200
    with environment.store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM care_explanations").fetchone()[0] == 1
        clear_database(db, other.id)
        assert db.execute("SELECT COUNT(*) FROM care_explanations").fetchone()[0] == 0
