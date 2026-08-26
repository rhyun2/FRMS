"""앱 내 알림 (FR-601).

전이 매트릭스의 ``notify`` 토큰을 실제 사용자로 해석해 알림 레코드를 만든다.
Phase 2의 이메일 발송(FR-605)과 Phase 3의 Teams 알림(FR-804)은 **이 함수의 발행
지점에 어댑터를 하나 더 붙이는 것**으로 구현한다 (docs/platform-decision.md 7절).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .enums import RegressionTarget, Role
from .models import FeatureRequest, Notification, User, UserRole
from .workflow import (
    NOTIFY_ALL_OWNERS,
    NOTIFY_DEV_OWNER,
    NOTIFY_QA_OWNER,
    NOTIFY_REGRESSION_OWNER,
    NOTIFY_REQUESTER,
    NOTIFY_ROLE_DEV,
    NOTIFY_ROLE_UI,
    NOTIFY_UI_OWNER,
    Transition,
)

if TYPE_CHECKING:  # pragma: no cover
    from .models import StatusTransition


def _users_with_role(db: Session, role: Role) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .join(UserRole)
            .where(UserRole.role == role.value, User.is_active.is_(True))
        )
    )


def _regression_owner(fr: FeatureRequest) -> User | None:
    rework = fr.open_rework
    if rework is None:
        return None
    return {
        RegressionTarget.REQUIREMENT: fr.requester,
        RegressionTarget.UI: fr.ui_owner,
        RegressionTarget.DEV: fr.dev_owner,
    }[rework.regression_target]


def resolve_targets(
    db: Session, fr: FeatureRequest, tokens: Iterable[str]
) -> list[User]:
    """알림 대상 토큰을 실제 사용자 목록으로. 중복과 비활성 사용자는 제거한다."""
    resolved: dict[str, User] = {}

    def add(user: User | None) -> None:
        if user is not None and user.is_active:
            resolved[user.id] = user

    for token in tokens:
        if token == NOTIFY_REQUESTER:
            add(fr.requester)
        elif token == NOTIFY_DEV_OWNER:
            add(fr.dev_owner)
        elif token == NOTIFY_UI_OWNER:
            add(fr.ui_owner)
        elif token == NOTIFY_QA_OWNER:
            add(fr.qa_owner)
        elif token == NOTIFY_ALL_OWNERS:
            for owner in (fr.requester, fr.dev_owner, fr.ui_owner, fr.qa_owner):
                add(owner)
        elif token == NOTIFY_ROLE_DEV:
            for user in _users_with_role(db, Role.DEV):
                add(user)
        elif token == NOTIFY_ROLE_UI:
            for user in _users_with_role(db, Role.UI):
                add(user)
        elif token == NOTIFY_REGRESSION_OWNER:
            add(_regression_owner(fr))

    return list(resolved.values())


def notify_targets(
    db: Session,
    *,
    fr: FeatureRequest,
    transition: Transition,
    actor: User,
    record: "StatusTransition",
) -> list[Notification]:
    """전이 결과를 알린다. 행위자 본인에게는 보내지 않는다."""
    targets = [u for u in resolve_targets(db, fr, transition.notify) if u.id != actor.id]

    message = (
        f"{fr.fr_key} · {fr.title} — "
        f"{actor.display_name}님이 '{transition.label}'을(를) 수행했습니다. "
        f"현재 단계: {transition.target.label}"
    )

    created = []
    for user in targets:
        notification = Notification(
            user_id=user.id,
            feature_request_id=fr.id,
            type=transition.action,
            message=message,
        )
        db.add(notification)
        created.append(notification)
    return created
