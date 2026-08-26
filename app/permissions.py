"""필드 그룹별 편집 권한. docs/data-model.md 6.2절을 선언 테이블로 옮긴 것이다.

수정 권한은 역할뿐 아니라 **현재 상태**에도 걸린다 (FR-103). 핵심은 이것이다:

    승인 이후(UI설계 단계부터) 요청 정보는 직접 수정할 수 없다.
    바꾸려면 보완요청(회귀 대상 = REQUIREMENT)을 거쳐야 한다.

이 제약이 있어야 "요구사항이 조용히 바뀌어 개발이 헛돌았다"는 사고(PRD 문제 P4)가
이력에 남는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .enums import RegressionTarget, Role, Status

if TYPE_CHECKING:  # pragma: no cover
    from .models import FeatureRequest, User


@dataclass(frozen=True)
class FieldGroup:
    key: str
    label: str
    fields: tuple[str, ...]
    #: 이 그룹을 편집할 수 있는 역할
    role: Role
    #: 편집 역할이 FR에 지정된 담당자여야 하는 경우의 슬롯. None이면 역할 보유만으로 가능.
    owner_slot: str | None
    #: 편집 가능한 상태
    statuses: tuple[Status, ...]
    #: REWORK 상태에서는 이 회귀 대상일 때만 편집 가능 (None이면 REWORK에서 항상 가능)
    rework_target: RegressionTarget | None = None


REQUEST_INFO = FieldGroup(
    key="request",
    label="요청 정보",
    fields=(
        "title",
        "background",
        "description",
        "acceptance_criteria",
        "product",
        "category",
        "priority",
        "desired_due_date",
    ),
    role=Role.BIZ,
    owner_slot="requester_id",
    statuses=(
        Status.DRAFT,
        Status.SUBMITTED,
        Status.REVIEW,
        Status.ON_HOLD,
        Status.REWORK,
    ),
    rework_target=RegressionTarget.REQUIREMENT,
)

PLAN_INFO = FieldGroup(
    key="plan",
    label="계획 정보",
    fields=(
        "dev_owner_id",
        "ui_owner_id",
        "qa_owner_id",
        "estimate_md",
        "target_due_date",
        "ui_change_required",
    ),
    role=Role.DEV,
    owner_slot="dev_owner_id",
    statuses=(
        Status.REVIEW,
        Status.UI_DESIGN,
        Status.IN_DEV,
        Status.DEV_DONE,
        Status.REWORK,
    ),
)

UI_INFO = FieldGroup(
    key="ui",
    label="UI 정보",
    fields=("ui_design_url",),
    role=Role.UI,
    owner_slot="ui_owner_id",
    statuses=(Status.REVIEW, Status.UI_DESIGN, Status.IN_DEV, Status.REWORK),
)

TEST_INFO = FieldGroup(
    key="test",
    label="검수 정보",
    fields=("test_result_summary", "test_env"),
    role=Role.QA,
    owner_slot="qa_owner_id",
    statuses=(Status.DEV_DONE, Status.IN_TEST, Status.REWORK),
)

FIELD_GROUPS: tuple[FieldGroup, ...] = (REQUEST_INFO, PLAN_INFO, UI_INFO, TEST_INFO)

GROUP_BY_FIELD: dict[str, FieldGroup] = {
    name: group for group in FIELD_GROUPS for name in group.fields
}


FIELD_LABELS: dict[str, str] = {
    "title": "제목",
    "background": "배경·목적",
    "description": "상세 내용",
    "acceptance_criteria": "완료 조건",
    "product": "대상 제품",
    "category": "기능 구분",
    "priority": "우선순위",
    "desired_due_date": "희망 완료일",
    "dev_owner_id": "개발담당",
    "ui_owner_id": "UI담당",
    "qa_owner_id": "검수담당",
    "estimate_md": "예상 공수(MD)",
    "target_due_date": "목표 완료일",
    "ui_change_required": "UI 변경 필요",
    "ui_design_url": "설계 산출물 링크",
    "dev_result_summary": "개발결과 요약",
    "test_env": "검증 환경",
    "test_result_summary": "검수 결과 요약",
}


def can_edit_group(group: FieldGroup, fr: "FeatureRequest", user: "User") -> bool:
    """이 사용자가 지금 이 FR에서 해당 필드 그룹을 편집할 수 있는가."""
    if fr.status.is_terminal and not user.has_role(Role.ADMIN):
        return False

    if user.has_role(Role.ADMIN):
        return True

    if fr.status not in group.statuses:
        return False

    # REWORK 상태에서는 열린 보완요청의 회귀 대상이 맞아야 한다.
    if fr.status is Status.REWORK and group.rework_target is not None:
        rework = fr.open_rework
        if rework is None or rework.regression_target != group.rework_target:
            return False

    if not user.has_role(group.role):
        return False

    if group.owner_slot is not None:
        return getattr(fr, group.owner_slot, None) == user.id

    return True


def editable_groups(fr: "FeatureRequest", user: "User") -> list[FieldGroup]:
    return [g for g in FIELD_GROUPS if can_edit_group(g, fr, user)]


def can_edit_field(field_name: str, fr: "FeatureRequest", user: "User") -> bool:
    group = GROUP_BY_FIELD.get(field_name)
    if group is None:
        return False
    return can_edit_group(group, fr, user)


def editable_fields(fr: "FeatureRequest", user: "User") -> set[str]:
    return {f for g in editable_groups(fr, user) for f in g.fields}


def denial_reason(group: FieldGroup, fr: "FeatureRequest", user: "User") -> str:
    """편집이 거부된 이유를 사용자에게 설명한다.

    특히 '승인 이후 요건 변경'은 왜 막혔는지와 무엇을 해야 하는지를 함께 알려야
    사용자가 시스템을 우회하지 않는다.
    """
    if fr.status.is_terminal:
        return f"종결된 요구사항({fr.status.label})은 수정할 수 없습니다."
    if fr.status not in group.statuses:
        if group is REQUEST_INFO:
            return (
                f"승인 이후({fr.status.label}) 요청 정보는 직접 수정할 수 없습니다. "
                "변경이 필요하면 보완요청(회귀 대상: 요건)을 통해 요건검토로 되돌리세요."
            )
        return f"{group.label}는 {fr.status.label} 단계에서 수정할 수 없습니다."
    if not user.has_role(group.role):
        return f"{group.label}는 {group.role.label}만 수정할 수 있습니다."
    return f"이 요구사항에 지정된 {group.role.label}만 수정할 수 있습니다."
