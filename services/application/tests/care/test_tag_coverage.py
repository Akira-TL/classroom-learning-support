import pytest
from test_evidence import Environment
from test_evidence import environment as environment
from test_tags import batch, periods


@pytest.mark.parametrize("outside", ["tag", "transcript"])
def test_known_capture_duration_rejects_outside_timestamps(environment: Environment, outside: str):
    payload = batch(duration=2000)
    if outside == "tag":
        payload["tags"][0]["end_ms"] = 2001
    else:
        payload["transcripts"] = [{"start_ms": 1500, "end_ms": 2001, "text": "带时间戳的外部转写"}]
    response = environment.client.post(f"/api/classrooms/{environment.cid}/care/tag-batches", json=payload)
    assert response.status_code == 422
    assert "采集时长" in response.text
    assert environment.client.get(f"/api/classrooms/{environment.cid}/care/tag-batches").json() == []


def test_exact_end_boundary_and_unknown_duration_are_supported(environment: Environment):
    payload = batch(duration=2000)
    payload["transcripts"] = [{"start_ms": 1500, "end_ms": 2000, "text": "恰好到采集结尾"}]
    url = f"/api/classrooms/{environment.cid}/care/tag-batches"
    assert environment.client.post(url, json=payload).status_code == 200
    unknown = batch("2026-10-24", duration=None)
    unknown["transcripts"] = [{"start_ms": 1500, "end_ms": 4000, "text": "采集时长未提供"}]
    assert environment.client.post(url, json=unknown).status_code == 200
    comparison = environment.client.post("/api/care/tag-comparison", json=periods()).json()
    assert comparison["summaries"][0]["baseline_per_hour"] is None
    assert all("教师核验" not in note for note in comparison["notes"])


@pytest.mark.parametrize("change", [
    {"import_id": "duplicate-import"},
    {"import_id": "duplicate-name", "source_name": "renamed.wav"},
    {"import_id": "duplicate-date", "observed_on": "2026-10-24"},
    {"import_id": "duplicate-version", "source_version": "v2"},
])
def test_same_session_cannot_inflate_counts_or_duration(environment: Environment, change):
    payload = batch(duration=3600000)
    url = f"/api/classrooms/{environment.cid}/care/tag-batches"
    imported = environment.client.post(url, json=payload)
    assert imported.status_code == 200
    assert environment.client.post(url, json=payload).json()["id"] == imported.json()["id"]
    response = environment.client.post(url, json=payload | change)
    assert response.status_code == 409 and "PUT" in response.text
    compared = environment.client.post("/api/care/tag-comparison", json=periods()).json()
    cough = compared["summaries"][0]
    assert cough["current_count"] == 6 and cough["current_duration_ms"] == 3600000
    assert cough["current_per_hour"] == 6 and cough["baseline_count"] is None
    assert len(compared["current"]) == 1
    revised = environment.client.put(f"{url}/{imported.json()['id']}", json=payload | {
        "expected_revision": 1, "source_version": "v2", "tags": payload["tags"] + [{
            "tag_id": "second-cough", "label": "cough", "original_label": "咳嗽",
            "category": "audible_event", "start_ms": 3000, "end_ms": 4000, "count": 1}]})
    assert revised.status_code == 200 and revised.json()["revision"] == 2
    final = environment.client.post("/api/care/tag-comparison", json=periods()).json()["summaries"][0]
    assert final["current_count"] == 7 and final["current_duration_ms"] == 3600000
