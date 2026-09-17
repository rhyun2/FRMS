"""도메인 서비스 — 전이 실행과 필드 수정.

모든 쓰기 경로가 여기를 지나므로, 권한 검증(FR-202)·필수 입력 검증(FR-203)·
이력 기록(FR-701·FR-702)이 한 곳에서 보장된다. 라우터는 HTTP 껍데기일 뿐이다.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import workflow
from .enums import (
    Category,
    Priority,
    RegressionTarget,
    Role,
    Severity,
    Status,
)
from .models import (
    FeatureRequest,
    FieldChange,
    KeySequence,
    Notification,
    ReworkRequest,
    StatusTransition,
    User,
    utcnow,
)
from .notifications import notify_targets
from .permissions import (
    FIELD_LABELS,
    GROUP_BY_FIELD,
    can_edit_field,
    denial_reason,
)
from .workflow import Input, Transition


class WorkflowError(Exception):
    """전이 또는 수정이 규칙에 의해 거부되었다.

    ``status`` 는 HTTP 응답 코드로 그대로 쓴다. 권한 문제는 403, 입력·상태 문제는 400.
    """

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# FR 키 채번 (FR-109)
# ---------------------------------------------------------------------------


def next_fr_key(db: Session, *, today: date | None = None) -> str:
    """``FR-YYYY-NNNN``. 연도별로 0001부터. 취소·반려된 번호도 재사용하지 않는다."""
    year = (today or date.today()).year
    seq = db.get(KeySequence, year, with_for_update=False)
    if seq is None:
        seq = KeySequence(year=year, last_number=0)
        db.add(seq)
    seq.last_number += 1
    db.flush()
    return f"FR-{year}-{seq.last_number:04d}"


# ---------------------------------------------------------------------------
# 입력 파싱
# ---------------------------------------------------------------------------


def _parse_value(spec: Input, raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None

    if spec.kind == "date":
        if isinstance(raw, date):
            return raw
        try:
            return date.fromisoformat(str(raw))
        except ValueError as exc:
            raise WorkflowError(f"{spec.label}: 날짜 형식이 올바르지 않습니다.") from exc

    if spec.kind == "number":
        try:
            return Decimal(str(raw))
        except (InvalidOperation, ValueError) as exc:
            raise WorkflowError(f"{spec.label}: 숫자를 입력하세요.") from exc

    if spec.kind == "select_choice":
        valid = {code for code, _ in spec.choices}
        if str(raw) not in valid:
            raise WorkflowError(f"{spec.label}: 허용되지 않은 값입니다.")
        return str(raw)

    return raw


def _resolve_user(db: Session, user_id: str, spec: Input) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise WorkflowError(f"{spec.label}: 존재하지 않는 사용자입니다.")
    if not user.is_active:
        raise WorkflowError(f"{spec.label}: 비활성 사용자는 담당자로 지정할 수 없습니다.")
    if spec.user_role is not None and not user.has_role(spec.user_role):
        raise WorkflowError(
            f"{spec.label}: {user.display_name}님은 {spec.user_role.label} 역할이 아닙니다."
        )
    return user


# ---------------------------------------------------------------------------
# 요구사항 생성 (T01 / FR-101)
# ---------------------------------------------------------------------------


def create_feature_request(
    db: Session, *, actor: User, values: dict[str, Any]
) -> FeatureRequest:
    transition = workflow.CREATION_TRANSITION

    if not workflow.satisfies_actor(transition, None, actor):
        raise WorkflowError(
            f"요구사항 등록은 {workflow.actor_description(transition)}만 할 수 있습니다.",
            status=403,
        )

    missing = transition.missing_inputs(values)
    if missing:
        raise WorkflowError("필수 항목이 비어 있습니다: " + ", ".join(missing))

    try:
        category = Category(str(values["category"]).strip())
    except ValueError as exc:
        raise WorkflowError("기능 구분: 허용되지 않은 값입니다.") from exc

    fr = FeatureRequest(
        fr_key=next_fr_key(db),
        title=str(values["title"]).strip(),
        description=str(values["description"]).strip(),
        product=str(values["product"]).strip(),
        category=category,
        background=(values.get("background") or None),
        status=Status.DRAFT,
        requester_id=actor.id,
    )
    db.add(fr)
    db.flush()

    _record_transition(
        db,
        fr=fr,
        transition=transition,
        actor=actor,
        from_status=None,
        payload={"title": fr.title},
        comment=None,
    )
    db.flush()
    return fr


# ---------------------------------------------------------------------------
# 전이 실행 (FR-201 ~ FR-203)
# ---------------------------------------------------------------------------


def perform_transition(
    db: Session,
    *,
    fr: FeatureRequest,
    transition_id: str,
    actor: User,
    values: dict[str, Any] | None = None,
) -> FeatureRequest:
    """전이 매트릭스에 정의된 전이만 수행한다. 정의되지 않은 조합은 거부된다."""
    values = values or {}
    transition = workflow.find(transition_id)
    if transition is None or transition.is_creation:
        raise WorkflowError(f"알 수 없는 전이입니다: {transition_id}")

    if fr.status not in transition.sources:
        raise WorkflowError(
            f"{fr.status.label} 상태에서는 '{transition.label}'을(를) 할 수 없습니다."
        )

    if not workflow.satisfies_actor(transition, fr, actor):
        raise WorkflowError(
            f"'{transition.label}'은(는) {workflow.actor_description(transition)}만 "
            "수행할 수 있습니다.",
            status=403,
        )

    if transition.guard is not None and not transition.guard(fr):
        raise WorkflowError(
            f"'{transition.label}'의 조건이 맞지 않습니다. "
            "보완요청의 회귀 대상을 확인하세요.",
            status=403,
        )

    # FR-102: 전이 전에 FR에 이미 채워져 있어야 하는 필드
    missing_fields = transition.missing_fields(fr)
    if missing_fields:
        raise WorkflowError(
            "먼저 다음 항목을 입력하세요: " + ", ".join(missing_fields)
        )

    # FR-203: 전이 시점에 받는 필수 입력
    missing_inputs = transition.missing_inputs(values)
    if missing_inputs:
        raise WorkflowError("필수 입력이 비어 있습니다: " + ", ".join(missing_inputs))

    from_status = fr.status
    payload: dict[str, Any] = {}
    comment: str | None = None

    for spec in transition.inputs:
        value = _parse_value(spec, values.get(spec.name))
        if value is None:
            continue

        if spec.kind == "select_user":
            user = _resolve_user(db, str(value), spec)
            value = user.id
            payload[spec.name] = user.display_name
        else:
            payload[spec.name] = str(value)

        if spec.name == "comment":
            comment = str(value)

        if spec.target_field:
            _apply_field(db, fr, spec.target_field, value, actor)

    for name, forced in transition.effects.items():
        _apply_field(db, fr, name, forced, actor)

    # 보완요청 생성·접수는 전이의 부수효과가 아니라 도메인 이벤트다.
    if transition.target is Status.REWORK:
        _open_rework(db, fr=fr, transition=transition, actor=actor, values=values)
    elif from_status is Status.REWORK:
        _accept_rework(db, fr=fr, actor=actor)

    fr.status = transition.target
    _stamp_milestones(fr, transition)

    if transition.target in (Status.REJECTED, Status.CANCELED) and comment:
        fr.closed_reason = comment

    record = _record_transition(
        db,
        fr=fr,
        transition=transition,
        actor=actor,
        from_status=from_status,
        payload=payload or None,
        comment=comment,
    )

    notify_targets(db, fr=fr, transition=transition, actor=actor, record=record)
    db.flush()
    return fr


def _stamp_milestones(fr: FeatureRequest, transition: Transition) -> None:
    """리드타임·체류시간 계산의 기준점. 최초 도달 시각만 남긴다."""
    now = utcnow()
    if transition.action == "SUBMIT" and fr.submitted_at is None:
        fr.submitted_at = now
    elif transition.action in ("APPROVE_WITH_UI", "APPROVE_NO_UI") and fr.approved_at is None:
        fr.approved_at = now
    elif transition.action == "DEV_DONE" and fr.dev_done_at is None:
        fr.dev_done_at = now
    elif transition.action == "PASS" and fr.done_at is None:
        fr.done_at = now


def _open_rework(
    db: Session,
    *,
    fr: FeatureRequest,
    transition: Transition,
    actor: User,
    values: dict[str, Any],
) -> ReworkRequest:
    target = RegressionTarget(str(values["regression_target"]))
    severity = Severity(str(values["severity"]))

    rework = ReworkRequest(
        sequence_no=fr.rework_count + 1,
        source_status=fr.status,
        regression_target=target,
        severity=severity,
        reason=str(values["reason"]).strip(),
        discovery_context=(values.get("discovery_context") or None),
        raised_by_id=actor.id,
    )
    fr.reworks.append(rework)  # db.add()를 함께 호출하지 않는다 (위 주석 참조)
    fr.rework_count += 1  # FR-303
    db.flush()
    return rework


def _accept_rework(db: Session, *, fr: FeatureRequest, actor: User) -> None:
    rework = fr.open_rework
    if rework is None:
        return
    rework.accepted_by_id = actor.id
    rework.accepted_at = utcnow()
    db.flush()


def _acting_role(transition: Transition, fr: FeatureRequest | None, actor: User) -> Role:
    """이력에 남길 '수행 시점의 역할'.

    ADMIN 권한으로 수행한 전이는 ADMIN으로 남겨 일반 전이와 구분한다. 단, 본인이
    정당한 담당자이기도 하면 그 역할을 우선한다.
    """
    for clause in transition.actors:
        if isinstance(clause, workflow.SlotClause):
            if fr is not None and getattr(fr, clause.slot, None) == actor.id:
                return {
                    "requester_id": Role.BIZ,
                    "dev_owner_id": Role.DEV,
                    "ui_owner_id": Role.UI,
                    "qa_owner_id": Role.QA,
                }[clause.slot]
        elif actor.has_role(clause.role):
            return clause.role
    return Role.ADMIN


def _record_transition(
    db: Session,
    *,
    fr: FeatureRequest,
    transition: Transition,
    actor: User,
    from_status: Status | None,
    payload: dict[str, Any] | None,
    comment: str | None,
) -> StatusTransition:
    record = StatusTransition(
        from_status=from_status,
        to_status=transition.target,
        transition_id=transition.id,
        action_code=transition.action,
        actor_id=actor.id,
        actor_role=_acting_role(transition, fr, actor),
        comment=comment,
        payload=payload,
    )
    # 관계에 append 하는 것만으로 FK 설정과 INSERT가 모두 일어난다.
    # db.add() 를 함께 호출하면 아직 로드되지 않은 컬렉션이 뒤늦게 로드되면서
    # 같은 객체가 메모리상 두 번 들어간다(DB 행은 하나). 이력 화면의 건수가 어긋난다.
    fr.transitions.append(record)
    return record


# ---------------------------------------------------------------------------
# 필드 수정 (FR-103 / FR-702)
# ---------------------------------------------------------------------------

_ENUM_FIELDS = {
    "priority": Priority,
    "category": Category,
}
_DATE_FIELDS = {"desired_due_date", "target_due_date"}
_USER_FIELDS = {
    "dev_owner_id": Role.DEV,
    "ui_owner_id": Role.UI,
    "qa_owner_id": Role.QA,
}


def _coerce_field(db: Session, name: str, raw: Any) -> Any:
    if isinstance(raw, str):
        raw = raw.strip()
    if raw in (None, ""):
        return None

    if name in _ENUM_FIELDS:
        try:
            return _ENUM_FIELDS[name](str(raw))
        except ValueError as exc:
            raise WorkflowError(
                f"{FIELD_LABELS.get(name, name)}: 허용되지 않은 값입니다."
            ) from exc

    if name in _DATE_FIELDS:
        if isinstance(raw, date):
            return raw
        try:
            return date.fromisoformat(str(raw))
        except ValueError as exc:
            raise WorkflowError(
                f"{FIELD_LABELS.get(name, name)}: 날짜 형식이 올바르지 않습니다."
            ) from exc

    if name == "estimate_md":
        try:
            return Decimal(str(raw))
        except (InvalidOperation, ValueError) as exc:
            raise WorkflowError("예상 공수(MD): 숫자를 입력하세요.") from exc

    if name == "ui_change_required":
        return str(raw).lower() in ("1", "true", "on", "yes")

    if name in _USER_FIELDS:
        user = db.get(User, str(raw))
        if user is None:
            raise WorkflowError(f"{FIELD_LABELS.get(name, name)}: 존재하지 않는 사용자입니다.")
        if not user.is_active:
            raise WorkflowError(
                f"{FIELD_LABELS.get(name, name)}: 비활성 사용자는 지정할 수 없습니다."
            )
        role = _USER_FIELDS[name]
        if not user.has_role(role):
            raise WorkflowError(
                f"{FIELD_LABELS.get(name, name)}: {user.display_name}님은 "
                f"{role.label} 역할이 아닙니다."
            )
        return user.id

    return raw


def _display(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:1000]


def _apply_field(
    db: Session, fr: FeatureRequest, name: str, value: Any, actor: User
) -> None:
    """값을 바꾸고 변경 이력을 남긴다. 권한은 호출자가 이미 검증한 상태여야 한다."""
    old = getattr(fr, name, None)
    if old == value:
        return
    setattr(fr, name, value)
    fr.field_changes.append(
        FieldChange(
            field_name=name,
            old_value=_display(old),
            new_value=_display(value),
            actor_id=actor.id,
        )
    )


def update_fields(
    db: Session, *, fr: FeatureRequest, actor: User, values: dict[str, Any]
) -> list[str]:
    """제출된 값 중 편집 권한이 있는 필드만 반영한다.

    권한 없는 필드가 하나라도 섞여 있으면 **전체를 거부**한다. 조용히 무시하면
    사용자는 저장됐다고 믿는다.
    """
    changed: list[str] = []
    staged: list[tuple[str, Any]] = []

    for name, raw in values.items():
        if name not in GROUP_BY_FIELD:
            continue
        if not can_edit_field(name, fr, actor):
            group = GROUP_BY_FIELD[name]
            raise WorkflowError(denial_reason(group, fr, actor), status=403)
        staged.append((name, _coerce_field(db, name, raw)))

    for name, value in staged:
        old = getattr(fr, name, None)
        if old != value:
            _apply_field(db, fr, name, value, actor)
            changed.append(FIELD_LABELS.get(name, name))

    if changed:
        fr.updated_at = utcnow()
    db.flush()
    return changed


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------


def get_by_key(db: Session, fr_key: str) -> FeatureRequest | None:
    return db.scalar(select(FeatureRequest).where(FeatureRequest.fr_key == fr_key))


def list_feature_requests(
    db: Session,
    *,
    include_terminal: bool = False,
    statuses: Sequence[Status] | None = None,
) -> list[FeatureRequest]:
    stmt = select(FeatureRequest)
    if statuses:
        stmt = stmt.where(FeatureRequest.status.in_([s.value for s in statuses]))
    elif not include_terminal:
        stmt = stmt.where(
            FeatureRequest.status.notin_([s.value for s in Status if s.is_terminal])
        )
    return list(db.scalars(stmt.order_by(FeatureRequest.created_at.desc())))


def my_queue(db: Session, user: User) -> list[FeatureRequest]:
    """FR-503: 지금 이 사용자에게 **처리가 기대되는** FR.

    판정 기준이 역할이 아니라 전이 매트릭스에서 파생되므로 규칙이 한 벌로 유지된다.
    정렬은 지연 → 우선순위 → 목표 완료일 (PRD 7.4절).

    단, 취소·반려 같은 파괴적 전이는 판정에서 제외한다. 취소(T22)는 사업담당이라면
    진행 중인 거의 모든 건에 대해 가능하므로, 그것까지 세면 사업담당의 큐가 "취소할 수
    있는 건 전부"가 되어 버린다. 큐는 "내가 다음 행동을 해야 하는 것"이어야지
    "내가 손댈 수 있는 것"이 아니다.
    """
    priority_order = {
        Priority.P0: 0,
        Priority.P1: 1,
        Priority.P2: 2,
        Priority.P3: 3,
        None: 4,
    }
    candidates = list_feature_requests(db, include_terminal=True)
    actionable = [
        fr
        for fr in candidates
        if any(
            not t.destructive for t in workflow.available_transitions(fr, user)
        )
    ]
    return sorted(
        actionable,
        key=lambda fr: (
            not fr.is_overdue,
            priority_order.get(fr.priority, 4),
            fr.target_due_date or date.max,
        ),
    )


def list_active_users(db: Session) -> list[User]:
    return list(
        db.scalars(
            select(User).where(User.is_active.is_(True)).order_by(User.display_name)
        )
    )


def users_by_role(db: Session) -> dict[Role, list[User]]:
    """담당자 선택 드롭다운의 후보. 비활성 사용자는 제외한다 (FR-204)."""
    everyone = list_active_users(db)
    return {role: [u for u in everyone if u.has_role(role)] for role in Role}


def unread_notification_count(db: Session, user: User) -> int:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .count()
    )


def recent_notifications(db: Session, user: User, limit: int = 20) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
    )


def mark_notifications_read(db: Session, user: User) -> None:
    db.query(Notification).filter(
        Notification.user_id == user.id, Notification.read_at.is_(None)
    ).update({Notification.read_at: utcnow()}, synchronize_session=False)
    db.flush()
