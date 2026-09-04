"""FRMS 애플리케이션 진입점.

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import workflow
from .config import get_settings
from .db import init_db
from .routers import admin, auth, board, fr
from .templating import TEMPLATE_DIR, templates

logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 전이 매트릭스가 구조적으로 깨진 채 기동하면 권한·버튼·큐가 전부 어긋난다.
    # 문서(docs/roadmap.md 4.5절)의 상태머신 완전성 검증을 기동 시점에도 건다.
    problems = workflow.validate_matrix()
    if problems:
        raise RuntimeError(
            "전이 매트릭스에 결함이 있습니다:\n  - " + "\n  - ".join(problems)
        )
    init_db()
    logger.info(
        "FRMS 기동 완료 (인증 모드: %s)",
        "Entra ID SSO" if settings.sso_enabled else "개발용 로컬 로그인",
    )
    yield


app = FastAPI(title=settings.app_name, docs_url="/api/docs", lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)

app.mount(
    "/static",
    StaticFiles(directory=str(TEMPLATE_DIR.parent / "static")),
    name="static",
)

app.include_router(auth.router)
app.include_router(board.router)
app.include_router(fr.router)
app.include_router(admin.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """인증 실패는 로그인 화면으로, 나머지는 사람이 읽을 수 있는 오류 화면으로."""
    if exc.status_code == 401:
        return RedirectResponse("/login", status_code=303)

    accepts_html = "text/html" in request.headers.get("accept", "")
    if not accepts_html:
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "user": None,
            "status_code": exc.status_code,
            "detail": exc.detail,
            "nav": "",
            "unread": 0,
        },
        status_code=exc.status_code,
    )


@app.get("/healthz", response_class=HTMLResponse, include_in_schema=False)
def healthz() -> str:
    return "ok"
