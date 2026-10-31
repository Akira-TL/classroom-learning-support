import pytest
from test_evidence import Environment
from test_evidence import environment as environment


def batch(day: str = "2026-10-31", count: int = 6, duration: int | None = None):
    return {"import_id": f"provided-{day}", "student_id": "student-01", "observed_on": day,
            "session_id": f"recording-{day}", "source_name": f"sample-{day}.wav", "source_version": "v1",
            "source_description": "用户提供的外部标签与时间戳，尚未校验算法准确率",
            "data_origin": "demonstration", "capture_conditions": "同一设备和距离",
            "captured_duration_ms": duration, "identity_confirmed": False, "confirmed": False,
            "tags": [{"tag_id": "cough01", "label": "cough", "original_label": "咳嗽",
                      "category": "audible_event", "start_ms": 1000, "end_ms": 2000, "count": count}]}


def periods():
    return {"student_id": "student-01", "baseline_start": "2026-10-19", "baseline_end": "2026-10-25",
            "current_start": "2026-10-26", "current_end": "2026-11-01"}


def test_unverified_external_import_participates_without_transcript_or_manual_approval(environment: Environment):
    url = f"/api/classrooms/{environment.cid}/care/tag-batches"
    response = environment.client.post(url, json=batch())
    assert response.status_code == 200 and response.json()["confirmed"] is False
    comparison = environment.client.post("/api/care/tag-comparison", json=periods()).json()
    cough = comparison["summaries"][0]
    assert cough["current_count"] == 6 and cough["baseline_count"] is None
    assert cough["current_per_hour"] is None and cough["rate_difference"] is None
    assert any("缺失不视为零" in note for note in cough["notes"])
    assert environment.client.post(url, json=batch()).json()["id"] == response.json()["id"]
    assert environment.client.post(url, json=batch(count=10)).status_code == 409


def test_known_durations_support_rates_and_different_conditions_prevent_rate_delta(environment: Environment):
    url = f"/api/classrooms/{environment.cid}/care/tag-batches"
    assert environment.client.post(url, json=batch("2026-10-24", 2, 1800000)).status_code == 200
    recent = environment.client.post(url, json=batch(count=6, duration=3600000)).json()
    result = environment.client.post("/api/care/tag-comparison", json=periods()).json()["summaries"][0]
    assert result["baseline_per_hour"] == 4 and result["current_per_hour"] == 6
    assert result["count_difference"] == 4 and result["rate_difference"] == 2
    changed = batch(count=6, duration=3600000) | {"expected_revision": 1, "capture_conditions": "不同设备和距离"}
    assert environment.client.put(f"{url}/{recent['id']}", json=changed).status_code == 200
    result = environment.client.post("/api/care/tag-comparison", json=periods()).json()["summaries"][0]
    assert result["rate_difference"] is None


@pytest.mark.parametrize("invalid", [
    {"label": "inattention", "category": "audible_event"}, {"count": -1}, {"end_ms": 500},
])
def test_invalid_tag_semantics_are_rejected(environment: Environment, invalid):
    payload = batch()
    payload["tags"][0].update(invalid)
    response = environment.client.post(f"/api/classrooms/{environment.cid}/care/tag-batches", json=payload)
    assert response.status_code == 422


def test_only_owning_teacher_may_import_or_read_student_history(environment: Environment):
    for username in ("parent-01", "student-01", "teacher-02", "admin-01"):
        environment.client.post("/api/auth/login", json={"username": username, "password": "evidence-test-password"})
        response = environment.client.post(f"/api/classrooms/{environment.cid}/care/tag-batches", json=batch())
        assert response.status_code == 403
