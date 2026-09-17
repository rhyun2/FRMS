"""SQLAlchemy 모델. docs/data-model.md 7절 필드 사전을 그대로 옮긴 것이다.

Phase 1 범위이므로 comment / attachment 는 만들지 않는다 (Phase 2, FR-602·FR-604).
notification 은 앱 내 알림(FR-601)이 Phase 1 범위이므로 포함한다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .enums import (
    Category,
    Priority,
    RegressionTarget,
    Role,
    Severity,
    Status,
)


class EnumType(TypeDecorator):
    """StrEnum을 VARCHAR로 저장하되 읽을 때 다시 열거형으로 되돌린다.

    ``Mapped[Status]`` 에 그냥 ``String`` 을 쓰면 저장은 되지만 조회 시 평범한 ``str``
    이 돌아온다. 그러면 ``fr.status is Status.IN_DEV`` 같은 비교가 조용히 False가 되어
    보드 컬럼이 비고 전이 판정이 어긋난다. 열거형 비교가 코드 전반의 판정 근거이므로
    양방향 변환을 타입 수준에서 보장한다.
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_cls, length: int = 16, **kwargs):
        self.enum_cls = enum_cls
        super().__init__(length=length, **kwargs)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return self.enum_cls(value).value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return self.enum_cls(value)


def _uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """저장은 UTC. 표시만 Asia/Seoul (PRD 8절 비기능 요구사항)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    #: Entra ID 사용자 고유값. 개발 모드에서는 ``dev:<이메일 로컬파트>`` 를 넣는다.
    entra_object_id: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    def has_role(self, role: Role) -> bool:
        return any(r.role == role for r in self.roles)

    @property
    def role_set(self) -> set[Role]:
        return {r.role for r in self.roles}

    @property
    def role_labels(self) -> str:
        order = [Role.BIZ, Role.DEV, Role.UI, Role.QA, Role.ADMIN]
        held = self.role_set
        return ", ".join(r.label for r in order if r in held) or "역할 없음"

    @property
    def initials(self) -> str:
        return (self.display_name or self.email)[:2]

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 편의
        return f"<User {self.display_name} {sorted(r.value for r in self.role_set)}>"


class UserRole(Base):
    __tablename__ = "user_role"
    __table_args__ = (UniqueConstraint("user_id", "role", name="uq_user_role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    role: Mapped[Role] = mapped_column(EnumType(Role, 8))

    user: Mapped[User] = relationship(back_populates="roles")


class FeatureRequest(Base):
    __tablename__ = "feature_request"
    __table_args__ = (
        Index("ix_fr_status", "status"),
        Index("ix_fr_status_priority", "status", "priority"),
        Index("ix_fr_target_due_date", "target_due_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    fr_key: Mapped[str] = mapped_column(String(16), unique=True)

    # --- 요청 정보 (사업담당 편집) ---
    title: Mapped[str] = mapped_column(String(200))
    background: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text)
    acceptance_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    product: Mapped[str] = mapped_column(String(64))
    category: Mapped[Category] = mapped_column(EnumType(Category, 16))
    priority: Mapped[Priority | None] = mapped_column(EnumType(Priority, 4), nullable=True)
    desired_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    status: Mapped[Status] = mapped_column(EnumType(Status, 16), default=Status.DRAFT)

    # --- 담당자 ---
    requester_id: Mapped[str] = mapped_column(ForeignKey("user.id"))
    dev_owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    ui_owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    qa_owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )

    # --- 계획 정보 (개발담당 편집) ---
    ui_change_required: Mapped[bool] = mapped_column(Boolean, default=True)
    estimate_md: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    target_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # --- UI 정보 ---
    ui_design_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # --- 개발·검수 정보 ---
    dev_result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_env: Mapped[str | None] = mapped_column(String(120), nullable=True)
    test_result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    rework_count: Mapped[int] = mapped_column(Integer, default=0)
    closed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dev_done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    requester: Mapped[User] = relationship(foreign_keys=[requester_id], lazy="joined")
    dev_owner: Mapped[User | None] = relationship(
        foreign_keys=[dev_owner_id], lazy="joined"
    )
    ui_owner: Mapped[User | None] = relationship(
        foreign_keys=[ui_owner_id], lazy="joined"
    )
    qa_owner: Mapped[User | None] = relationship(
        foreign_keys=[qa_owner_id], lazy="joined"
    )

    transitions: Mapped[list["StatusTransition"]] = relationship(
        back_populates="feature_request",
        cascade="all, delete-orphan",
        order_by="StatusTransition.created_at",
        lazy="selectin",
    )
    reworks: Mapped[list["ReworkRequest"]] = relationship(
        back_populates="feature_request",
        cascade="all, delete-orphan",
        order_by="ReworkRequest.sequence_no",
        lazy="selectin",
    )
    field_changes: Mapped[list["FieldChange"]] = relationship(
        back_populates="feature_request",
        cascade="all, delete-orphan",
        order_by="FieldChange.created_at",
        lazy="selectin",
    )

    # --- 파생 속성 ---

    @property
    def open_rework(self) -> "ReworkRequest | None":
        """아직 접수되지 않은 보완요청. T18~T20 가드의 판정 근거."""
        for rework in reversed(self.reworks):
            if rework.accepted_at is None:
                return rework
        return None

    @property
    def is_overdue(self) -> bool:
        """지연 여부: 종결되지 않았고 목표 완료일이 지났다 (docs/data-model.md 9절)."""
        if self.status.is_terminal or self.target_due_date is None:
            return False
        return self.target_due_date < date.today()

    @property
    def days_remaining(self) -> int | None:
        """D-day. 음수면 지연 일수."""
        if self.target_due_date is None:
            return None
        return (self.target_due_date - date.today()).days

    @property
    def dday_label(self) -> str | None:
        days = self.days_remaining
        if days is None:
            return None
        if days == 0:
            return "D-day"
        return f"D-{days}" if days > 0 else f"D+{abs(days)}"

    @property
    def current_owner(self) -> User | None:
        """지금 공을 쥔 사람. 카드에 표시한다 (PRD 7.2절)."""
        return CURRENT_OWNER_RESOLVER.get(self.status, lambda fr: None)(self)

    def __repr__(self) -> str:  # pragma: no cover - 디버깅 편의
        return f"<FR {self.fr_key} {self.status}>"


def _regression_owner(fr: FeatureRequest) -> User | None:
    rework = fr.open_rework
    if rework is None:
        return None
    return {
        RegressionTarget.REQUIREMENT: fr.requester,
        RegressionTarget.UI: fr.ui_owner,
        RegressionTarget.DEV: fr.dev_owner,
    }[rework.regression_target]


#: 상태별로 "지금 공을 쥔 사람"이 누구인지. docs/data-model.md 3절의 '공을 쥔 역할' 열.
CURRENT_OWNER_RESOLVER = {
    Status.DRAFT: lambda fr: fr.requester,
    Status.SUBMITTED: lambda fr: fr.dev_owner,
    Status.REVIEW: lambda fr: fr.dev_owner,
    Status.ON_HOLD: lambda fr: fr.requester,
    Status.UI_DESIGN: lambda fr: fr.ui_owner,
    Status.IN_DEV: lambda fr: fr.dev_owner,
    Status.DEV_DONE: lambda fr: fr.dev_owner,
    Status.IN_TEST: lambda fr: fr.qa_owner,
    Status.REWORK: _regression_owner,
}


class StatusTransition(Base):
    """전이 이력. append-only — 애플리케이션 경로로 수정·삭제하지 않는다 (FR-701)."""

    __tablename__ = "status_transition"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    feature_request_id: Mapped[str] = mapped_column(
        ForeignKey("feature_request.id", ondelete="CASCADE")
    )
    from_status: Mapped[Status | None] = mapped_column(EnumType(Status, 16), nullable=True)
    to_status: Mapped[Status] = mapped_column(EnumType(Status, 16))
    transition_id: Mapped[str] = mapped_column(String(8))  # T01 ~ T22
    action_code: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(ForeignKey("user.id"))
    actor_role: Mapped[Role] = mapped_column(EnumType(Role, 8))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    feature_request: Mapped[FeatureRequest] = relationship(back_populates="transitions")
    actor: Mapped[User] = relationship(lazy="joined")


class ReworkRequest(Base):
    """보완요청. ``regression_target`` 이 이 시스템의 가장 중요한 단일 필드다."""

    __tablename__ = "rework_request"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    feature_request_id: Mapped[str] = mapped_column(
        ForeignKey("feature_request.id", ondelete="CASCADE")
    )
    sequence_no: Mapped[int] = mapped_column(Integer)
    source_status: Mapped[Status] = mapped_column(EnumType(Status, 16))
    regression_target: Mapped[RegressionTarget] = mapped_column(EnumType(RegressionTarget, 16))
    severity: Mapped[Severity] = mapped_column(EnumType(Severity, 8))
    reason: Mapped[str] = mapped_column(Text)
    discovery_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    raised_by_id: Mapped[str] = mapped_column(ForeignKey("user.id"))
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    accepted_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    feature_request: Mapped[FeatureRequest] = relationship(back_populates="reworks")
    raised_by: Mapped[User] = relationship(foreign_keys=[raised_by_id], lazy="joined")
    accepted_by: Mapped[User | None] = relationship(
        foreign_keys=[accepted_by_id], lazy="joined"
    )


class FieldChange(Base):
    """필드 변경 이력 (FR-702).

    기록은 소급이 불가능하므로 타임라인 UI(Phase 2)보다 먼저 남기기 시작한다.
    """

    __tablename__ = "field_change"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    feature_request_id: Mapped[str] = mapped_column(
        ForeignKey("feature_request.id", ondelete="CASCADE")
    )
    field_name: Mapped[str] = mapped_column(String(64))
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    feature_request: Mapped[FeatureRequest] = relationship(back_populates="field_changes")
    actor: Mapped[User] = relationship(lazy="joined")


class Notification(Base):
    """앱 내 알림 (FR-601). Phase 2에서 이메일 발송이 이 테이블을 소스로 붙는다."""

    __tablename__ = "notification"
    __table_args__ = (Index("ix_notification_user_read", "user_id", "read_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    feature_request_id: Mapped[str] = mapped_column(
        ForeignKey("feature_request.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    feature_request: Mapped[FeatureRequest] = relationship(lazy="joined")


class KeySequence(Base):
    """FR 키 채번용 연도별 카운터. ``FR-YYYY-NNNN`` (FR-109)."""

    __tablename__ = "key_sequence"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, default=0)
