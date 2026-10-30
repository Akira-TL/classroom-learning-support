"""由项目脚本创建本机服务，导入模块不创建数据库。"""

from pathlib import Path

from fastapi import FastAPI

from .api import create_app


def application() -> FastAPI:
    root = Path(__file__).resolve().parents[3]
    return create_app(root / "data" / "private" / "classroom.sqlite3")
