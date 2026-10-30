from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, TypeAdapter

from teaching.api import create_app
from teaching.classroom.auth import COOKIE_NAME, AuthSettings, User
from teaching.classroom.classrooms import Classroom, CreateClassroom, Question, UpdateClassroom

PASSWORD = "only-for-test-credentials"


@pytest.fixture
def settings() -> AuthSettings:
    return AuthSettings(demo_password=SecretStr(PASSWORD))


@pytest.fixture
def payload() -> CreateClassroom:
    return CreateClassroom(
        title="平均分",
        date=date(2026, 10, 31),
        objective="理解平均分条件",
        students=["student-01", "student-02", "student-03"],
        questions=[
            Question(
                id="q-01",
                text="四块一定各是四分之一吗？",
                reference_answer="必须平均分",
                diagram_required=True,
                diagram_description="同一个长方形分成面积不等的四块",
            )
        ],
        source="成人模拟录音",
        authorization="仅使用合成材料",
        idempotency_key="create-01",
    )


def login(client: TestClient, username: str = "teacher-01") -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200
    assert User.model_validate_json(response.content).id == username
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=strict" in response.headers["set-cookie"].lower()


def create(client: TestClient, payload: CreateClassroom) -> Classroom:
    response = client.post("/api/classrooms", content=payload.model_dump_json())
    assert response.status_code == 201
    return Classroom.model_validate_json(response.content)


def test_create_reopen_update_and_persistence(tmp_path: Path, settings: AuthSettings, payload: CreateClassroom) -> None:
    database = tmp_path / "classrooms.sqlite3"
    with TestClient(create_app(database, settings), headers={"Content-Type": "application/json"}) as client:
        login(client)
        original = create(client, payload)
        assert original.revision == 1
        assert original.teacher_id == "teacher-01"
        assert original.questions[0].diagram_description == "同一个长方形分成面积不等的四块"
        updated = UpdateClassroom(
            **payload.model_dump(exclude={"idempotency_key"}) | {"title": "平均分与四分之一"},
            expected_revision=1,
        )
        response = client.put(f"/api/classrooms/{original.id}", content=updated.model_dump_json())
        assert response.status_code == 200
        assert Classroom.model_validate_json(response.content).revision == 2
        assert client.put(f"/api/classrooms/{original.id}", content=updated.model_dump_json()).status_code == 409
    with TestClient(create_app(database, settings), headers={"Content-Type": "application/json"}) as client:
        login(client)
        response = client.get(f"/api/classrooms/{original.id}")
        assert Classroom.model_validate_json(response.content).title == "平均分与四分之一"
        listing = TypeAdapter(list[Classroom]).validate_json(client.get("/api/classrooms").content)
        assert [item.id for item in listing] == [original.id]


def test_idempotency_is_scoped_and_payload_conflicts(
    tmp_path: Path,
    settings: AuthSettings,
    payload: CreateClassroom,
) -> None:
    with TestClient(
        create_app(tmp_path / "db.sqlite3", settings), headers={"Content-Type": "application/json"}
    ) as client:
        login(client)
        first = create(client, payload)
        assert create(client, payload).id == first.id
        changed = payload.model_copy(update={"title": "不同内容"})
        assert client.post("/api/classrooms", content=changed.model_dump_json()).status_code == 409
        login(client, "teacher-02")
        assert create(client, payload).id != first.id


def test_teacher_ownership_and_roles_are_enforced(
    tmp_path: Path,
    settings: AuthSettings,
    payload: CreateClassroom,
) -> None:
    with TestClient(
        create_app(tmp_path / "db.sqlite3", settings), headers={"Content-Type": "application/json"}
    ) as client:
        assert client.get("/api/classrooms").status_code == 401
        login(client)
        first = create(client, payload)
        update = UpdateClassroom(**payload.model_dump(exclude={"idempotency_key"}), expected_revision=1)
        login(client, "teacher-02")
        assert client.get(f"/api/classrooms/{first.id}").status_code == 403
        assert client.put(f"/api/classrooms/{first.id}", content=update.model_dump_json()).status_code == 403
        assert TypeAdapter(list[Classroom]).validate_json(client.get("/api/classrooms").content) == []
        for username in ("student-01", "parent-01", "admin-01"):
            login(client, username)
            assert client.get(f"/api/classrooms/{first.id}").status_code == 403
            assert client.post("/api/classrooms", content=payload.model_dump_json()).status_code == 403


def test_logout_and_forged_identity(tmp_path: Path, settings: AuthSettings) -> None:
    with TestClient(
        create_app(tmp_path / "db.sqlite3", settings), headers={"Content-Type": "application/json"}
    ) as client:
        login(client, "parent-01")
        me = User.model_validate_json(client.get("/api/auth/me").content)
        assert me.role == "parent"
        assert me.student_id == "student-01"
        token = client.cookies.get(COOKIE_NAME)
        assert client.post("/api/auth/logout").status_code == 204
        client.cookies.set(COOKIE_NAME, token)
        assert client.get("/api/auth/me").status_code == 401
        assert (
            client.post(
                "/api/auth/login",
                json={
                    "username": "student-01",
                    "password": PASSWORD,
                    "role": "teacher",
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/auth/login",
                json={
                    "username": "teacher-01",
                    "password": "wrong-password",
                },
            ).status_code
            == 401
        )


def test_invalid_references_and_cross_origin_writes(
    tmp_path: Path,
    settings: AuthSettings,
    payload: CreateClassroom,
) -> None:
    with TestClient(
        create_app(tmp_path / "db.sqlite3", settings), headers={"Content-Type": "application/json"}
    ) as client:
        login(client)
        for students in (["real-student"], ["student-01", "student-01"]):
            invalid = payload.model_copy(update={"students": students})
            assert client.post("/api/classrooms", content=invalid.model_dump_json()).status_code == 422
        invalid = payload.model_copy(update={"questions": payload.questions * 2})
        assert client.post("/api/classrooms", content=invalid.model_dump_json()).status_code == 422
        response = client.post(
            "/api/classrooms",
            content=payload.model_dump_json(),
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403


def test_unconfigured_password_does_not_enable_accounts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="DEMO_PASSWORD"):
        create_app(tmp_path / "db.sqlite3")
