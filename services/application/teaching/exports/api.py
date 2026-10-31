from typing import Annotated

from fastapi import APIRouter, Depends, Response

from ..classroom.auth import User, require_teacher
from ..classroom.storage import SQLiteStore
from .models import CreateExport, ExportMetadata, RevokeExport
from .store import ExportStore


def exports_router(classroom_store: SQLiteStore) -> APIRouter:
    store = ExportStore(classroom_store)
    router = APIRouter(prefix="/api", tags=["教师报告导出"])

    @router.post("/classrooms/{cid}/exports", response_model=ExportMetadata)
    def create(cid: str, payload: CreateExport, user: Annotated[User, Depends(require_teacher)]) -> ExportMetadata:
        return store.create(cid, user.id, payload)

    @router.get("/classrooms/{cid}/exports", response_model=list[ExportMetadata])
    def listing(cid: str, user: Annotated[User, Depends(require_teacher)]) -> list[ExportMetadata]:
        return store.list(cid, user.id)

    @router.post("/classrooms/{cid}/exports/{export_id}/revoke", response_model=ExportMetadata)
    def revoke(
        cid: str,
        export_id: str,
        payload: RevokeExport,
        user: Annotated[User, Depends(require_teacher)],
    ) -> ExportMetadata:
        return store.revoke(cid, user.id, export_id, payload)

    @router.get("/exports/{export_id}/download", response_model=None)
    def download(export_id: str, user: Annotated[User, Depends(require_teacher)]) -> Response:
        content = store.download(export_id, user.id)
        return Response(
            content,
            media_type="text/html",
            headers={
                "Content-Disposition": f'attachment; filename="teacher-report-{export_id}.html"',
                "Content-Security-Policy": (
                    "sandbox allow-downloads; default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'"
                ),
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/exports/{export_id}/status", response_model=ExportMetadata)
    def status(export_id: str) -> ExportMetadata:
        return store.status(export_id)

    return router
