"""보드·내 할 일·목록 라우터 (FR-501, FR-503, FR-505, FR-509)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import services, workflow
from ..auth import current_user
from ..db import get_db
from ..enums import BOARD_COLUMNS, Priority, Status
from ..models import User
from ..templating import templates

router = APIRouter(tags=["board"])


@router.get("/")
def index():
    return RedirectResponse("/board", status_code=303)


@router.get("/board", response_class=HTMLResponse)
def board(
    request: Request,
    show_closed: bool = Query(False, description="보류·반려·취소도 표시"),
    mine: bool = Query(False, description="내가 관련된 건만"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """칸반 보드. 랜딩 화면이다 (PRD 7.2절).

    필터 조건은 쿼리스트링에 있으므로 화면 링크를 그대로 공유·북마크할 수 있다 (FR-509).
    """
    all_frs = services.list_feature_requests(db, include_terminal=True)

    if mine:
        all_frs = [fr for fr in all_frs if _is_related(fr, user)]

    # DRAFT는 작성자 본인에게만 별도 섹션으로 보인다. 남의 미완성 초안은 노이즈다.
    my_drafts = [
        fr for fr in all_frs if fr.status is Status.DRAFT and fr.requester_id == user.id
    ]

    columns = []
    for status in BOARD_COLUMNS:
        items = sorted(
            (fr for fr in all_frs if fr.status is status),
            key=lambda fr: (not fr.is_overdue, _priority_rank(fr)),
        )
        columns.append(
            {
                "status": status,
                # 키 이름을 items 로 두면 Jinja가 dict.items 메서드로 해석한다.
                "cards": items,
                "count": len(items),
                "overdue": sum(1 for fr in items if fr.is_overdue),
            }
        )

    closed = []
    if show_closed:
        for status in (Status.ON_HOLD, Status.REJECTED, Status.CANCELED):
            items = [fr for fr in all_frs if fr.status is status]
            closed.append({"status": status, "cards": items, "count": len(items)})

    return templates.TemplateResponse(
        request,
        "board.html",
        {
            "user": user,
            "columns": columns,
            "my_drafts": my_drafts,
            "closed": closed,
            "show_closed": show_closed,
            "mine": mine,
            "nav": "board",
            "unread": services.unread_notification_count(db, user),
        },
    )


@router.get("/my-queue", response_class=HTMLResponse)
def my_queue(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """FR-503: 지금 내가 처리할 수 있는 것만. 판정은 전이 매트릭스에서 파생된다."""
    items = services.my_queue(db, user)
    rows = [
        {"fr": fr, "transitions": workflow.available_transitions(fr, user)}
        for fr in items
    ]
    return templates.TemplateResponse(
        request,
        "my_queue.html",
        {
            "user": user,
            "rows": rows,
            "nav": "queue",
            "unread": services.unread_notification_count(db, user),
        },
    )


@router.get("/list", response_class=HTMLResponse)
def fr_list(
    request: Request,
    status: list[str] = Query(default=[]),
    priority: list[str] = Query(default=[]),
    owner: str = Query(default=""),
    product: str = Query(default=""),
    overdue_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """FR-104 / FR-505: 목록 뷰. 기본값은 종결되지 않은 전 건."""
    selected_statuses = [Status(s) for s in status if s in Status.__members__]
    items = services.list_feature_requests(
        db,
        include_terminal=bool(selected_statuses),
        statuses=selected_statuses or None,
    )

    if priority:
        wanted = {p for p in priority}
        items = [fr for fr in items if fr.priority and fr.priority.value in wanted]
    if owner:
        items = [fr for fr in items if _has_owner(fr, owner)]
    if product:
        items = [fr for fr in items if product.lower() in (fr.product or "").lower()]
    if overdue_only:
        items = [fr for fr in items if fr.is_overdue]

    return templates.TemplateResponse(
        request,
        "list.html",
        {
            "user": user,
            "items": items,
            "selected_statuses": {s.value for s in selected_statuses},
            "selected_priorities": set(priority),
            "owner": owner,
            "product": product,
            "overdue_only": overdue_only,
            "all_users": services.list_active_users(db),
            "nav": "list",
            "unread": services.unread_notification_count(db, user),
        },
    )


@router.get("/notifications", response_class=HTMLResponse)
def notifications(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    items = services.recent_notifications(db, user)
    services.mark_notifications_read(db, user)
    db.commit()
    return templates.TemplateResponse(
        request,
        "notifications.html",
        {"user": user, "items": items, "nav": "", "unread": 0},
    )


def _is_related(fr, user: User) -> bool:
    return user.id in {
        fr.requester_id,
        fr.dev_owner_id,
        fr.ui_owner_id,
        fr.qa_owner_id,
    }


def _has_owner(fr, user_id: str) -> bool:
    return user_id in {
        fr.requester_id,
        fr.dev_owner_id,
        fr.ui_owner_id,
        fr.qa_owner_id,
    }


def _priority_rank(fr) -> int:
    return {Priority.P0: 0, Priority.P1: 1, Priority.P2: 2, Priority.P3: 3}.get(
        fr.priority, 4
    )
