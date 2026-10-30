"""教师课堂接口；完整视觉界面另行实现。"""

from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint

from .audio.api import speech_router
from .audio.store import SpeechStore
from .classroom.auth import COOKIE_NAME, AuthSettings, DemoAuth, LoginRequest, User, current_user, require_teacher
from .classroom.classrooms import Classroom, CreateClassroom, UpdateClassroom
from .classroom.storage import SQLiteStore, StoreError
from .corrections.api import corrections_router
from .deletion.api import deletion_router
from .exercises.api import exercises_router
from .exports.api import exports_router
from .learning.api import learning_router
from .manual_exercises.api import manual_exercises_router
from .overview.api import overview_router
from .plans.api import plans_router
from .reports.api import reports_router
from .students.api import students_router


def create_app(database_path: Path, settings: AuthSettings | None = None) -> FastAPI:
    settings = settings or AuthSettings.from_environment()
    store = SQLiteStore(database_path)
    auth = DemoAuth(store, settings)
    app = FastAPI(title="课堂学习支持", version="0.1.0")
    app.state.store = store
    app.state.auth = auth
    speech = SpeechStore(database_path)
    app.state.speech = speech
    app.include_router(speech_router(store, speech))
    app.include_router(learning_router(store, speech))
    app.include_router(exercises_router(store))
    app.include_router(reports_router(store))
    app.include_router(plans_router(store))
    app.include_router(students_router(store))
    app.include_router(exports_router(store))
    app.include_router(corrections_router(store, speech))
    app.include_router(deletion_router(store))
    app.include_router(overview_router(store))
    app.include_router(manual_exercises_router(store))

    @app.middleware("http")
    async def check_origin(request: Request, call_next: RequestResponseEndpoint) -> Response:
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.url.netloc}"
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and origin
            and origin != expected
            and origin not in settings.trusted_origins
        ):
            return JSONResponse(status_code=403, content={"detail": "不接受跨来源写操作"})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(StoreError)
    async def store_error(_request: Request, error: StoreError) -> JSONResponse:
        return JSONResponse(status_code=error.status, content={"detail": str(error)})

    @app.post("/api/auth/login", response_model=User)
    def login(payload: LoginRequest, request: Request, response: Response) -> User:
        user, token = auth.login(payload)
        auth.logout(request.cookies.get(COOKIE_NAME))
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=settings.session_seconds,
            httponly=True,
            secure=settings.secure_cookie or request.url.scheme == "https",
            samesite="strict",
            path="/",
        )
        return user

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request, response: Response) -> None:
        auth.logout(request.cookies.get(COOKIE_NAME))
        response.delete_cookie(COOKIE_NAME, path="/")

    @app.get("/api/auth/me", response_model=User)
    def me(user: Annotated[User, Depends(current_user)]) -> User:
        return user

    @app.post("/api/classrooms", response_model=Classroom, status_code=201)
    def create(payload: CreateClassroom, user: Annotated[User, Depends(require_teacher)]) -> Classroom:
        return store.create_classroom(user.id, payload)

    @app.get("/api/classrooms", response_model=list[Classroom])
    def classrooms(user: Annotated[User, Depends(require_teacher)]) -> list[Classroom]:
        return store.list_classrooms(user.id)

    @app.get("/api/classrooms/{classroom_id}", response_model=Classroom)
    def classroom(classroom_id: str, user: Annotated[User, Depends(require_teacher)]) -> Classroom:
        return store.get_classroom(user.id, classroom_id)

    @app.put("/api/classrooms/{classroom_id}", response_model=Classroom)
    def update(
        classroom_id: str,
        payload: UpdateClassroom,
        user: Annotated[User, Depends(require_teacher)],
    ) -> Classroom:
        return store.update_classroom(user.id, classroom_id, payload)

    return app
