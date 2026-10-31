"""本机演示账号与服务端会话，不接受客户端自报角色。"""

import hashlib
import os
import secrets
import time
from typing import Literal, Self

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from .storage import SQLiteStore

COOKIE_NAME = "classroom_session"
DisplayRole = Literal["teacher", "head_teacher", "student", "parent", "teaching_director"]


class AuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    demo_password: SecretStr | None = Field(default=None, min_length=12)
    session_seconds: int = Field(default=28800, ge=60, le=86400)
    secure_cookie: bool = False
    trusted_origins: tuple[str, ...] = ("http://127.0.0.1:3000", "http://localhost:3000")

    @classmethod
    def from_environment(cls) -> "AuthSettings":
        password = os.getenv("DEMO_PASSWORD", "")
        return cls(demo_password=SecretStr(password) if len(password) >= 12 else None)


class User(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    role: Literal["teacher", "student", "parent", "admin"]
    student_id: str | None = None
    display_role: DisplayRole | None = None


USERS = (
    User(id="teacher-01", role="teacher"),
    User(id="teacher-02", role="teacher"),
    *(User(id=f"student-{number:02d}", role="student", student_id=f"student-{number:02d}") for number in range(1, 11)),
    User(id="parent-01", role="parent", student_id="student-01"),
    User(id="admin-01", role="admin"),
)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=100)
    password: SecretStr


class DemoLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: DisplayRole
    student_id: str | None = Field(default=None, pattern=r"^student-(0[1-9]|10)$")

    @model_validator(mode="after")
    def permitted_selection(self) -> Self:
        if self.student_id is not None and self.role not in {"student", "parent"}:
            raise ValueError("该演示角色不接受学生身份参数")
        if self.role == "parent" and self.student_id not in {None, "student-01"}:
            raise ValueError("当前固定家长演示身份仅绑定student-01")
        return self


class DemoAuth:
    def __init__(self, store: SQLiteStore, settings: AuthSettings) -> None:
        self.store = store
        self.settings = settings
        with store.connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS demo_session_roles "
                               "(token_hash TEXT PRIMARY KEY, display_role TEXT NOT NULL)")

    def login(self, request: LoginRequest) -> tuple[User, str]:
        if self.settings.demo_password is None:
            raise HTTPException(401, "账号密码入口未配置，请选择演示角色进入")
        user = next((user for user in USERS if user.id == request.username), None)
        valid = secrets.compare_digest(
            request.password.get_secret_value().encode(),
            self.settings.demo_password.get_secret_value().encode(),
        )
        if user is None or not valid:
            raise HTTPException(401, "账号或密码错误")
        display_role = "teaching_director" if user.role == "admin" else user.role
        return self._issue(user.model_copy(update={"display_role": display_role}))

    def demo_login(self, request: DemoLoginRequest) -> tuple[User, str]:
        selected = {
            "teacher": "teacher-01", "head_teacher": "teacher-01", "student": request.student_id or "student-01",
            "parent": "parent-01", "teaching_director": "admin-01",
        }[request.role]
        user = next(user for user in USERS if user.id == selected)
        return self._issue(user.model_copy(update={"display_role": request.role}))

    def _issue(self, user: User) -> tuple[User, str]:
        token = secrets.token_urlsafe(32)
        with self.store.connection() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
            connection.execute("DELETE FROM demo_session_roles WHERE token_hash NOT IN "
                               "(SELECT token_hash FROM sessions)")
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?)",
                (self._hash(token), user.id, int(time.time()) + self.settings.session_seconds),
            )
            connection.execute("INSERT INTO demo_session_roles VALUES (?,?)", (self._hash(token), user.display_role))
        return user, token

    def user(self, token: str | None) -> User:
        if not token:
            raise HTTPException(401, "请先登录")
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT s.user_id,r.display_role FROM sessions s LEFT JOIN demo_session_roles r "
                "ON s.token_hash=r.token_hash WHERE s.token_hash=? AND s.expires_at>?",
                (self._hash(token), int(time.time())),
            ).fetchone()
        user = next((user for user in USERS if row and user.id == row["user_id"]), None)
        if user is None:
            raise HTTPException(401, "会话已失效，请重新登录")
        display = row["display_role"] or ("teaching_director" if user.role == "admin" else user.role)
        return User.model_validate(user.model_dump() | {"display_role": display})

    def logout(self, token: str | None) -> None:
        if token:
            with self.store.connection() as connection:
                connection.execute("DELETE FROM sessions WHERE token_hash=?", (self._hash(token),))
                connection.execute("DELETE FROM demo_session_roles WHERE token_hash=?", (self._hash(token),))

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()


def current_user(request: Request) -> User:
    return request.app.state.auth.user(request.cookies.get(COOKIE_NAME))


def require_teacher(request: Request) -> User:
    user = current_user(request)
    if user.role != "teacher":
        raise HTTPException(403, "此操作需要教师权限")
    return user
