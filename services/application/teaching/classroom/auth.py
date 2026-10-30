"""本机演示账号与服务端会话，不接受客户端自报角色。"""

import hashlib
import os
import secrets
import time
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .storage import SQLiteStore

COOKIE_NAME = "classroom_session"


class AuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    demo_password: SecretStr = Field(min_length=12)
    session_seconds: int = Field(default=28800, ge=60, le=86400)
    secure_cookie: bool = False
    trusted_origins: tuple[str, ...] = ("http://127.0.0.1:3000", "http://localhost:3000")

    @classmethod
    def from_environment(cls) -> "AuthSettings":
        password = os.getenv("DEMO_PASSWORD", "")
        if len(password) < 12:
            raise RuntimeError("需在本机配置至少12位 DEMO_PASSWORD，演示账号未启用")
        return cls(demo_password=SecretStr(password))


class User(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    role: Literal["teacher", "student", "parent", "admin"]
    student_id: str | None = None


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


class DemoAuth:
    def __init__(self, store: SQLiteStore, settings: AuthSettings) -> None:
        self.store = store
        self.settings = settings

    def login(self, request: LoginRequest) -> tuple[User, str]:
        user = next((user for user in USERS if user.id == request.username), None)
        valid = secrets.compare_digest(
            request.password.get_secret_value().encode(),
            self.settings.demo_password.get_secret_value().encode(),
        )
        if user is None or not valid:
            raise HTTPException(401, "账号或密码错误")
        token = secrets.token_urlsafe(32)
        with self.store.connection() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?)",
                (self._hash(token), user.id, int(time.time()) + self.settings.session_seconds),
            )
        return user, token

    def user(self, token: str | None) -> User:
        if not token:
            raise HTTPException(401, "请先登录")
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?",
                (self._hash(token), int(time.time())),
            ).fetchone()
        user = next((user for user in USERS if row and user.id == row["user_id"]), None)
        if user is None:
            raise HTTPException(401, "会话已失效，请重新登录")
        return user

    def logout(self, token: str | None) -> None:
        if token:
            with self.store.connection() as connection:
                connection.execute("DELETE FROM sessions WHERE token_hash=?", (self._hash(token),))

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
