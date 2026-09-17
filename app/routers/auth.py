"""로그인·로그아웃 라우터."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import (
    current_user_optional,
    get_oauth,
    login_session,
    logout_session,
    upsert_from_claims,
)
from ..config import get_settings
from ..db import get_db
from ..models import User, utcnow
from ..templating import templates

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    if current_user_optional(request, db) is not None:
        return RedirectResponse("/board", status_code=status.HTTP_303_SEE_OTHER)

    dev_users = []
    if not settings.sso_enabled:
        dev_users = list(
            db.scalars(
                select(User).where(User.is_active.is_(True)).order_by(User.display_name)
            )
        )

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "sso_enabled": settings.sso_enabled,
            "dev_users": dev_users,
            "user": None,
        },
    )


@router.post("/auth/dev-login")
def dev_login(
    request: Request, user_id: str = Form(...), db: Session = Depends(get_db)
):
    """개발용 로컬 로그인. Entra 설정이 있으면 사용할 수 없다."""
    settings = get_settings()
    if settings.sso_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SSO가 활성화되어 개발용 로그인은 사용할 수 없습니다.",
        )

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    user.last_login_at = utcnow()
    db.commit()
    login_session(request, user)
    return RedirectResponse("/board", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/auth/login")
async def sso_login(request: Request):
    settings = get_settings()
    oauth = get_oauth(settings)
    if oauth is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return await oauth.entra.authorize_redirect(request, settings.entra_redirect_uri)


@router.get("/auth/callback")
async def sso_callback(request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    oauth = get_oauth(settings)
    if oauth is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    token = await oauth.entra.authorize_access_token(request)
    claims = token.get("userinfo") or {}
    if not claims:
        raise HTTPException(status_code=400, detail="사용자 정보를 가져오지 못했습니다.")

    user = upsert_from_claims(db, claims)
    db.commit()
    login_session(request, user)
    return RedirectResponse("/board", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout")
def logout(request: Request):
    logout_session(request)
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
