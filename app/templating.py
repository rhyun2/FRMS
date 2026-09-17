"""Jinja2 템플릿 환경과 화면에서 쓰는 헬퍼."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from . import workflow
from .config import get_settings
from .enums import (
    BOARD_COLUMNS,
    STEPPER_STEPS,
    Category,
    Priority,
    RegressionTarget,
    Role,
    Severity,
    Status,
)
from .permissions import FIELD_LABELS

TEMPLATE_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

_display_tz = ZoneInfo(get_settings().timezone_display)


def localtime(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """저장은 UTC, 표시는 Asia/Seoul (PRD 8절)."""
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_display_tz).strftime(fmt)


def localdate(value, fmt: str = "%Y-%m-%d") -> str:
    if value is None:
        return "-"
    return value.strftime(fmt)


def stepper_state(fr, step: Status) -> str:
    """진행 스테퍼의 각 단계 상태: done / current / skipped / pending.

    docs/PRD.md 7.3절. UI 변경이 없는 건은 UI설계 단계를 '생략됨'으로 표기한다.
    """
    if step is Status.UI_DESIGN and not fr.ui_change_required:
        return "skipped"

    if fr.status is step:
        return "current"

    order = list(STEPPER_STEPS)
    # 진행 중이 아닌 상태(작성중/보류/반려/취소/보완요청)는 스테퍼 위치를 따로 잡는다.
    anchor = {
        Status.DRAFT: -1,
        Status.ON_HOLD: order.index(Status.REVIEW),
        Status.REJECTED: order.index(Status.REVIEW),
        Status.CANCELED: -1,
        Status.REWORK: order.index(Status.IN_TEST),
    }.get(fr.status)

    current_index = anchor if anchor is not None else order.index(fr.status)
    step_index = order.index(step)

    if step_index < current_index:
        return "done"
    if step_index == current_index:
        return "current"
    return "pending"


def priority_rank(fr) -> int:
    return {Priority.P0: 0, Priority.P1: 1, Priority.P2: 2, Priority.P3: 3}.get(
        fr.priority, 4
    )


templates.env.filters["localtime"] = localtime
templates.env.filters["localdate"] = localdate

templates.env.globals.update(
    BOARD_COLUMNS=BOARD_COLUMNS,
    STEPPER_STEPS=STEPPER_STEPS,
    Status=Status,
    Role=Role,
    Priority=Priority,
    Category=Category,
    RegressionTarget=RegressionTarget,
    Severity=Severity,
    FIELD_LABELS=FIELD_LABELS,
    stepper_state=stepper_state,
    available_transitions=workflow.available_transitions,
    app_name=get_settings().app_name,
)
