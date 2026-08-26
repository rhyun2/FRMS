"""인증 (FR-401).

Entra ID OIDC를 구현하되, 클라이언트 설정이 없으면 **개발용 로컬 로그인**으로 동작한다.
어느 쪽이든 자체 비밀번호는 저장하지 않는다.

개발 모드는 `settings.sso_enabled` 가 False일 때만 켜지므로, 운영 환경에 Entra 설정을
넣는 순간 로컬 로그인 경로는 닫힌다.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_db
from .models import User, UserRole, utcnow

SESSION_USER_KEY = "user_id"


def get_oauth(settings: Settings):
    """Authlib OAuth 클라이언트. SSO가 꺼져 있으면 None."""
    if not settings.sso_enabled:
        return None
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="entra",
        client_id=settings.entra_client_id,
        client_secret=settings.entra_client_secret,
        server_metadata_url=settings.oidc_metadata_url,
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth


def upsert_from_claims(db: Session, claims: dict[str, Any]) -> User:
    """Entra ID 클레임으로 사용자 레코드를 만들거나 갱신한다 (FR-401).

    최초 로그인 사용자는 **역할 없이** 생성된다. 역할 부여는 관리자의 명시적 행위다
    (FR-402) — 로그인만으로 권한이 생기면 안 된다.
    """
    oid = str(claims.get("oid") or claims.get("sub"))
    email = str(claims.get("email") or claims.get("preferred_username") or "")
    name = str(claims.get("name") or email or oid)

    user = db.scalar(select(User).where(User.entra_object_id == oid))
    if user is None:
        user = User(entra_object_id=oid, email=email, display_name=name)
        db.add(user)
    else:
        user.email = email or user.email
        user.display_name = name or user.display_name
    user.last_login_at = utcnow()
    db.flush()
    return user


def login_session(request: Request, user: User) -> None:
    request.session[SESSION_USER_KEY] = user.id


def logout_session(request: Request) -> None:
    request.session.pop(SESSION_USER_KEY, None)


def current_user_optional(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        request.session.pop(SESSION_USER_KEY, None)
        return None
    return user


def current_user(user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다."
        )
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    from .enums import Role

    if not user.has_role(Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="관리자만 접근할 수 있습니다."
        )
    return user


def set_roles(db: Session, user: User, roles: set) -> None:
    """FR-402: 사용자의 역할 집합을 통째로 교체한다."""
    existing = {r.role: r for r in user.roles}
    for role, row in existing.items():
        if role not in roles:
            db.delete(row)
            user.roles.remove(row)
    for role in roles:
        if role not in existing:
            user.roles.append(UserRole(user_id=user.id, role=role))
    db.flush()
