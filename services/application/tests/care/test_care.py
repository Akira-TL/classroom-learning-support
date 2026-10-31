from datetime import date

import pytest
from test_evidence import Environment
from test_evidence import environment as environment

from teaching.audio.models import ReviewRequest
from teaching.care.models import AcousticMeasurements, Observation
from teaching.classroom.classrooms import CreateClassroom, Question


@pytest.fixture
def ready(environment: Environment) -> Environment:
    environment.verify()
    return environment


def observe(env: Environment, cid: str | None = None, observed_on: str = "2026-10-31"):
    return env.client.post(f"/api/classrooms/{cid or env.cid}/care/observations", json={
        "session_id": "s-1", "segment_id": "u-1", "expected_utterance_version": 2,
        "student_id": "student-01", "observed_on": observed_on, "fact": "主动回答一次分数问题",
        "capture_conditions": "同一设备、固定距离、同一教室", "teacher_note": "下课询问解题过程", "confirmed": True,
    })


def periods():
    return {"student_id": "student-01", "baseline_start": "2026-10-19", "baseline_end": "2026-10-25",
            "current_start": "2026-10-26", "current_end": "2026-11-01"}


def create_report(env: Environment):
    comparison = env.client.post("/api/care/compare", json=periods()).json()
    basis = [{"observation_id": item["id"], "revision": item["revision"]}
             for item in comparison["baseline"] + comparison["current"]]
    return env.client.post(f"/api/classrooms/{env.cid}/care/reports", json={
        "comparison": periods(), "basis": basis, "teacher_text": "教师内部观察和待了解情况",
        "student_text": "你的解题过程值得继续记录", "parent_text": "请了解孩子本周课堂体验",
        "followup": "教师周五课后面谈，并记录学生自己的描述",
    })


def login(env: Environment, username: str):
    return env.client.post("/api/auth/login", json={"username": username, "password": "evidence-test-password"})


def test_observation_requires_verified_identity_and_real_classroom_date(environment: Environment) -> None:
    assert observe(environment).status_code == 409
    environment.verify()
    wrong_date = observe(environment, observed_on="2026-10-24")
    assert wrong_date.status_code == 422
    response = observe(environment)
    assert response.status_code == 200
    assert response.json()["measurements"] is None
    assert "上游尚未" in response.json()["measurement_note"]
    invalid = response.json()
    for key in ("id", "revision", "classroom_id", "teacher_id", "source_current", "measurement_note"):
        invalid.pop(key)
    invalid["measurements"] = {"pitch_hz": 0}
    invalid_response = environment.client.post(f"/api/classrooms/{environment.cid}/care/observations", json=invalid)
    assert invalid_response.status_code == 422
    assert observe(environment).status_code == 409


def test_two_periods_compare_same_student_and_keep_missing_measurements(ready: Environment) -> None:
    assert observe(ready).status_code == 200
    earlier = ready.store.create_classroom("teacher-01", CreateClassroom(
        title="上周分数课", date=date(2026, 10, 24), objective="理解平均分", students=["student-01"],
        questions=[Question(id="q-1", text="四块就是四分之一吗", reference_answer="需要平均分")],
        source="synthetic", authorization="成人模拟", idempotency_key="care-baseline"))
    ready.speech.receive(earlier.id, ready.event)
    ready.speech.review(earlier.id, "s-1", "u-1", "teacher-01", ReviewRequest(
        expected_version=1, text_review="confirmed", identity_review="confirmed", question_review="pending",
        student_alias="student-01"))
    assert observe(ready, earlier.id, "2026-10-24").status_code == 200
    compared = ready.client.post("/api/care/compare", json=periods())
    assert compared.status_code == 200
    result = compared.json()
    assert len(result["baseline"]) == len(result["current"]) == 1
    assert result["metrics"][0]["difference"] is None
    assert result["metrics"][0]["current_mean"] is None
    assert any("样本不足" in note for note in result["notes"])
    assert ready.client.post("/api/care/compare", json=periods() | {"student_id": "student-02"}).json()["current"] == []
    login(ready, "teacher-02")
    assert ready.client.post("/api/care/compare", json=periods()).json()["current"] == []


def test_publish_separates_audiences_and_source_change_immediately_hides(ready: Environment) -> None:
    assert observe(ready).status_code == 200
    response = create_report(ready)
    assert response.status_code == 200
    report = response.json()
    base = f"/api/classrooms/{ready.cid}/care/reports/{report['id']}/action"
    login(ready, "parent-01")
    assert ready.client.get("/api/care/me").json() == []
    assert ready.client.post(base, json={"action": "publish", "expected_revision": 1,
                                       "teacher_confirmed": True}).status_code == 403
    login(ready, "teacher-01")
    assert ready.client.post(base, json={"action": "publish", "expected_revision": 1,
                                       "teacher_confirmed": False}).status_code == 422
    assert ready.client.post(base, json={"action": "publish", "expected_revision": 1,
                                       "teacher_confirmed": True}).status_code == 200
    for username, expected in (("parent-01", "请了解孩子本周课堂体验"), ("student-01", "你的解题过程值得继续记录")):
        login(ready, username)
        result = ready.client.get("/api/care/me").json()
        assert result[0]["text"] == expected
        assert "teacher_text" not in result[0] and "basis" not in result[0] and "followup" not in result[0]
    login(ready, "student-02")
    assert ready.client.get("/api/care/me").json() == []
    ready.speech.receive(ready.cid, ready.event.model_copy(update={
        "event_id": "care-corrected", "event_type": "revision", "revision": 2, "sequence": 10, "text": "纠正后的发言"}))
    login(ready, "parent-01")
    assert ready.client.get("/api/care/me").json() == []
    login(ready, "teacher-01")
    assert ready.client.get(f"/api/classrooms/{ready.cid}/care/reports").json()[0]["status"] == "stale"


def test_changed_observation_cannot_publish_old_draft_and_revoke_is_effective(ready: Environment) -> None:
    observation = observe(ready).json()
    report = create_report(ready).json()
    edited = {key: observation[key] for key in (
        "session_id", "segment_id", "expected_utterance_version", "student_id", "observed_on", "fact",
        "capture_conditions", "teacher_note", "confirmed")}
    edited.update(expected_revision=1, fact="更正为教师点名后回答")
    observation_url = f"/api/classrooms/{ready.cid}/care/observations/{observation['id']}"
    assert ready.client.put(observation_url, json=edited).status_code == 200
    action = {"action": "publish", "expected_revision": 1, "teacher_confirmed": True}
    report_url = f"/api/classrooms/{ready.cid}/care/reports/{report['id']}/action"
    assert ready.client.post(report_url, json=action).status_code == 409
    report2 = create_report(ready).json()
    url = f"/api/classrooms/{ready.cid}/care/reports/{report2['id']}/action"
    assert ready.client.post(url, json=action).status_code == 200
    assert ready.client.post(url, json=action | {"action": "revoke", "expected_revision": 2}).status_code == 200
    login(ready, "parent-01")
    assert ready.client.get("/api/care/me").json() == []


def test_numeric_difference_requires_enough_same_method_and_conditions(ready: Environment) -> None:
    from teaching.care.compare import metric

    value = observe(ready).json()
    observation = Observation.model_validate(value)
    before = [observation.model_copy(update={"measurements": AcousticMeasurements(
        reliability="verified", method="test_measurement", pitch_hz=pitch)}) for pitch in (100, 110, 120)]
    after = [observation.model_copy(update={"measurements": AcousticMeasurements(
        reliability="verified", method="test_measurement", pitch_hz=pitch)}) for pitch in (120, 130, 140)]
    result = metric("pitch_hz", "Hz", before, after, True)
    assert result.baseline_mean == 110 and result.current_mean == 130 and result.difference == 20
    assert metric("pitch_hz", "Hz", before[:1], after, True).difference is None
    assert metric("pitch_hz", "Hz", before, after, False).difference is None
    altered = after[0].model_copy(update={"measurements": AcousticMeasurements(
        reliability="verified", method="different_measurement", pitch_hz=120)})
    assert metric("pitch_hz", "Hz", before, [altered, *after[1:]], True).difference is None


def test_acoustic_measurements_only_accept_explicit_valid_upstream_measurement(ready: Environment) -> None:
    from teaching.care.store import measurements
    from teaching.integration.native_models import NativeSpeechEvent

    source = ready.speech.timeline(ready.cid)[0]
    native = NativeSpeechEvent(session_id="s-1", event_id="metrics", sequence=1,
                               event_type="transcript.final", segment_id="u-1", text="平均分")
    assert measurements(source.model_copy(update={"native_event": native})) is None
    invalid = native.model_copy(update={"diagnostics": {"acoustic_measurements": {
        "method": "test_method", "reliability": "verified", "pitch_hz": 0}}})
    assert measurements(source.model_copy(update={"native_event": invalid})) is None
    valid = native.model_copy(update={"diagnostics": {"acoustic_measurements": {
        "method": "test_method", "reliability": "verified", "pitch_hz": 210, "level_dbfs": -24}}})
    result = measurements(source.model_copy(update={"native_event": valid}))
    assert result and result.pitch_hz == 210 and result.level_dbfs == -24


def test_classroom_deletion_removes_care_data_and_recipient_access(ready: Environment) -> None:
    from teaching.deletion.database import clear_database

    assert observe(ready).status_code == 200
    report = create_report(ready).json()
    url = f"/api/classrooms/{ready.cid}/care/reports/{report['id']}/action"
    assert ready.client.post(url, json={"action": "publish", "expected_revision": 1,
                                       "teacher_confirmed": True}).status_code == 200
    with ready.store.connection() as db:
        clear_database(db, ready.cid)
        for table in ("care_observations", "care_reports"):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    login(ready, "parent-01")
    assert ready.client.get("/api/care/me").json() == []
