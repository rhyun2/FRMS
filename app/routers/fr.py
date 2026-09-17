"""요구사항 상세·등록·수정·전이 라우터."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status as http_status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import services, workflow
from ..auth import current_user
from ..db import get_db
from ..enums import Role, Status
from ..models import FeatureRequest, User
from ..permissions import FIELD_GROUPS, can_edit_group, editable_groups
from ..services import WorkflowError
from ..templating import templates

router = APIRouter(tags=["feature-request"])


def _load(db: Session, fr_key: str) -> FeatureRequest:
    fr = services.get_by_key(db, fr_key)
    if fr is None:
        raise HTTPException(status_code=404, detail="요구사항을 찾을 수 없습니다.")
    return fr


async def _form_values(request: Request) -> dict[str, str]:
    form = await request.form()
    return {k: v for k, v in form.multi_items() if isinstance(v, str)}


@router.get("/fr/new", response_class=HTMLResponse)
def new_form(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not user.has_role(Role.BIZ) and not user.has_role(Role.ADMIN):
        raise HTTPException(
            status_code=403, detail="요구사항 등록은 사업담당만 할 수 있습니다."
        )
    return templates.TemplateResponse(
        request,
        "fr_new.html",
        {
            "user": user,
            "nav": "new",
            "errors": [],
            "values": {},
            "unread": services.unread_notification_count(db, user),
        },
    )


@router.post("/fr/new")
async def create(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    values = await _form_values(request)
    try:
        fr = services.create_feature_request(db, actor=user, values=values)
    except WorkflowError as exc:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "fr_new.html",
            {
                "user": user,
                "nav": "new",
                "errors": [exc.message],
                "values": values,
                "unread": services.unread_notification_count(db, user),
            },
            status_code=exc.status,
        )
    db.commit()
    return RedirectResponse(f"/fr/{fr.fr_key}", status_code=http_status.HTTP_303_SEE_OTHER)


@router.get("/fr/{fr_key}", response_class=HTMLResponse)
def detail(
    request: Request,
    fr_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """상세 화면. 조회는 전 역할 전체 공개, 행동만 제한된다."""
    fr = _load(db, fr_key)
    return templates.TemplateResponse(
        request,
        "fr_detail.html",
        {
            "user": user,
            "fr": fr,
            # FR-208: 지금 이 사용자가 수행 가능한 전이만 버튼으로 노출한다.
            "transitions": workflow.available_transitions(fr, user),
            "groups": [
                (group, can_edit_group(group, fr, user)) for group in FIELD_GROUPS
            ],
            "editable": {g.key for g in editable_groups(fr, user)},
            "nav": "",
            "unread": services.unread_notification_count(db, user),
        },
    )


@router.get("/fr/{fr_key}/edit", response_class=HTMLResponse)
def edit_form(
    request: Request,
    fr_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    fr = _load(db, fr_key)
    groups = editable_groups(fr, user)
    if not groups:
        raise HTTPException(
            status_code=403,
            detail="이 요구사항에서 수정할 수 있는 항목이 없습니다.",
        )
    return templates.TemplateResponse(
        request,
        "fr_edit.html",
        {
            "user": user,
            "fr": fr,
            "groups": groups,
            "errors": [],
            "users_by_role": services.users_by_role(db),
            "nav": "",
            "unread": services.unread_notification_count(db, user),
        },
    )


@router.post("/fr/{fr_key}/edit")
async def edit(
    request: Request,
    fr_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    fr = _load(db, fr_key)
    values = await _form_values(request)
    try:
        services.update_fields(db, fr=fr, actor=user, values=values)
    except WorkflowError as exc:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "fr_edit.html",
            {
                "user": user,
                "fr": fr,
                "groups": editable_groups(fr, user),
                "errors": [exc.message],
                "users_by_role": services.users_by_role(db),
                "nav": "",
                "unread": services.unread_notification_count(db, user),
            },
            status_code=exc.status,
        )
    db.commit()
    return RedirectResponse(f"/fr/{fr_key}", status_code=http_status.HTTP_303_SEE_OTHER)


@router.get("/fr/{fr_key}/transition/{transition_id}", response_class=HTMLResponse)
def transition_form(
    request: Request,
    fr_key: str,
    transition_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """전이 다이얼로그. 필수 입력을 그 자리에서 받는다 (PRD 7.6절)."""
    fr = _load(db, fr_key)
    transition = workflow.find(transition_id)
    if transition is None or not workflow.can_perform(transition, fr, user):
        raise HTTPException(
            status_code=403, detail="이 전이를 수행할 권한이 없습니다."
        )
    return templates.TemplateResponse(
        request,
        "fr_transition.html",
        {
            "user": user,
            "fr": fr,
            "transition": transition,
            "errors": [],
            "values": {},
            "users_by_role": services.users_by_role(db),
            "nav": "",
            "unread": services.unread_notification_count(db, user),
        },
    )


@router.post("/fr/{fr_key}/transition/{transition_id}")
async def transition(
    request: Request,
    fr_key: str,
    transition_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """FR-201 ~ FR-203. 매트릭스에 없는 조합과 권한 없는 시도는 여기서 거부된다."""
    fr = _load(db, fr_key)
    values = await _form_values(request)

    try:
        services.perform_transition(
            db, fr=fr, transition_id=transition_id, actor=user, values=values
        )
    except WorkflowError as exc:
        db.rollback()
        transition = workflow.find(transition_id)
        if transition is None:
            raise HTTPException(status_code=400, detail=exc.message) from exc
        return templates.TemplateResponse(
            request,
            "fr_transition.html",
            {
                "user": user,
                "fr": _load(db, fr_key),
                "transition": transition,
                "errors": [exc.message],
                "values": values,
                "users_by_role": services.users_by_role(db),
                "nav": "",
                "unread": services.unread_notification_count(db, user),
            },
            status_code=exc.status,
        )

    db.commit()
    return RedirectResponse(f"/fr/{fr_key}", status_code=http_status.HTTP_303_SEE_OTHER)
