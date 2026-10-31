from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from teaching.api import create_app
from teaching.classroom.auth import COOKIE_NAME, AuthSettings, User


@pytest.mark.parametrize("display,actor,role,student", [
    ("teacher", "teacher-01", "teacher", None),
    ("head_teacher", "teacher-01", "teacher", None),
    ("student", "student-01", "student", "student-01"),
    ("parent", "parent-01", "parent", "student-01"),
    ("teaching_director", "admin-01", "admin", None),
])
def test_role_entry_has_fixed_subject_and_persistent_display_role(
    tmp_path: Path, display: str, actor: str, role: str, student: str | None,
):
    database = tmp_path / "db.sqlite3"
    with TestClient(create_app(database, AuthSettings())) as client:
        response = client.post("/api/auth/demo-login", json={"role": display})
        assert response.status_code == 200
        user = User.model_validate_json(response.content)
        assert (user.id, user.role, user.student_id, user.display_role) == (actor, role, student, display)
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
        token = client.cookies.get(COOKIE_NAME)
        assert client.get("/api/auth/me").json()["display_role"] == display
        if role != "teacher":
            assert client.get("/api/classrooms").status_code == 403
    with TestClient(create_app(database, AuthSettings())) as restarted:
        restarted.cookies.set(COOKIE_NAME, token)
        assert restarted.get("/api/auth/me").json()["display_role"] == display
        assert restarted.post("/api/auth/logout").status_code == 204
        restarted.cookies.set(COOKIE_NAME, token)
        assert restarted.get("/api/auth/me").status_code == 401


def test_student_selection_and_parent_binding_are_server_validated(tmp_path: Path):
    with TestClient(create_app(tmp_path / "db.sqlite3", AuthSettings())) as client:
        for number in range(1, 11):
            response = client.post("/api/auth/demo-login", json={
                "role": "student", "student_id": f"student-{number:02d}"})
            assert response.status_code == 200
            assert response.json()["id"] == response.json()["student_id"] == f"student-{number:02d}"
        parent = client.post("/api/auth/demo-login", json={"role": "parent", "student_id": "student-01"})
        assert parent.status_code == 200
        for invalid in (
            {"role": "parent", "student_id": "student-02"},
            {"role": "student", "student_id": "student-11"},
            {"role": "teacher", "student_id": "student-01"},
            {"role": "admin"},
            {"role": "teacher", "id": "teacher-02"},
            {"role": "parent", "display_role": "teacher"},
        ):
            assert client.post("/api/auth/demo-login", json=invalid).status_code == 422


def test_switching_demo_role_revokes_old_token_and_cross_origin_cannot_enter(tmp_path: Path):
    with TestClient(create_app(tmp_path / "db.sqlite3", AuthSettings())) as client:
        assert client.post("/api/auth/demo-login", json={"role": "head_teacher"}).status_code == 200
        previous = client.cookies.get(COOKIE_NAME)
        assert client.post("/api/auth/demo-login", json={"role": "student"}).status_code == 200
        current = client.cookies.get(COOKIE_NAME)
        assert previous != current
        client.cookies.set(COOKIE_NAME, previous)
        assert client.get("/api/auth/me").status_code == 401
        client.cookies.set(COOKIE_NAME, current)
        assert client.get("/api/auth/me").json()["role"] == "student"
        blocked = client.post("/api/auth/demo-login", json={"role": "teacher"},
                              headers={"Origin": "https://evil.example"})
        assert blocked.status_code == 403
        assert client.get("/api/auth/me").json()["role"] == "student"
