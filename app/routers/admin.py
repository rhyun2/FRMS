"""관리자 화면 — 사용자·역할 관리 (FR-402, FR-405)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..auth import require_admin, set_roles
from ..db import get_db
from ..enums import Role
from ..models import User
from ..templating import templates

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_class=HTMLResponse)
def users(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    all_users = list(db.scalars(select(User).order_by(User.display_name)))
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            "user": admin,
            "users": all_users,
            "roles": list(Role),
            "nav": "admin",
            "unread": services.unread_notification_count(db, admin),
        },
    )


@router.post("/users/{user_id}/roles")
async def update_roles(
    request: Request,
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    form = await request.form()
    selected = {Role(v) for v in form.getlist("roles") if v in Role.__members__}
    set_roles(db, target, selected)
    db.commit()
    return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/active")
def toggle_active(
    user_id: str,
    is_active: str = Form("false"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """FR-405: 비활성 사용자는 기존 이력을 보존하고 신규 담당자 지정에서만 제외된다."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="본인 계정은 비활성화할 수 없습니다.")

    target.is_active = is_active.lower() in ("1", "true", "on", "yes")
    db.commit()
    return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)
