from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from ..classroom.auth import User, current_user
from ..classroom.storage import SQLiteStore
from .models import AdminSummary
from .store import OverviewStore


def overview_router(classroom_store: SQLiteStore) -> APIRouter:
    overview = OverviewStore(classroom_store)
    router = APIRouter(prefix="/api/admin", tags=["管理者教学支持汇总"])

    @router.get("/summary", response_model=AdminSummary)
    def summary(request: Request, user: Annotated[User, Depends(current_user)]) -> AdminSummary:
        if user.role != "admin" or user.id != "admin-01":
            raise HTTPException(403, "需要固定演示管理者权限")
        if request.query_params:
            raise HTTPException(422, "汇总范围固定，不接受筛选或扩大授权范围的参数")
        return overview.summary()

    return router
