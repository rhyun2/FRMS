"""상태 전이 매트릭스 — 이 제품의 심장.

docs/data-model.md 5절의 표를 **코드 안 단일 선언 테이블**로 옮긴 것이다.
PRD 9절의 설계 원칙에 따라 다음 네 가지가 모두 이 테이블 하나에서 파생된다:

1. 전이 권한 검증 (FR-202)   -> :func:`can_perform`
2. 전이 필수 입력 검증 (FR-203) -> :func:`Transition.missing_inputs`
3. 화면의 전이 버튼 노출 (FR-208) -> :func:`available_transitions`
4. "내 할 일" 큐 (FR-503)      -> :func:`available_transitions` 가 비어 있지 않은 FR

규칙을 여러 곳에 흩어 두면 반드시 어긋나므로, 새 전이나 권한 변경은 오직 이 파일의
:data:`TRANSITIONS` 만 고친다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Iterable, Sequence

from .enums import (
    Category,
    Priority,
    RegressionTarget,
    Role,
    Severity,
    Status,
)

if TYPE_CHECKING:  # pragma: no cover - 순환 임포트 방지용
    from .models import FeatureRequest, User


# ---------------------------------------------------------------------------
# 행위자 규칙
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleClause:
    """해당 역할을 보유한 사용자면 누구나 수행할 수 있다.

    담당자가 아직 지정되지 않은 전이(T03·T04)나, 조직 차원의 판단인 전이
    (T07 보류 · T09 재개 · T10 번복 · T18 요건 보완접수)에만 쓴다.
    """

    role: Role

    def describe(self) -> str:
        return f"{self.role.label} 역할 보유자"


@dataclass(frozen=True)
class SlotClause:
    """해당 FR에 **지정된 담당자 본인**만 수행할 수 있다 (FR-202).

    역할만 보유하고 이 FR에 지정되지 않은 제3자는 전이할 수 없다. 이것이
    "누가 공을 쥐고 있는가"를 시스템이 강제하는 방식이다.
    """

    slot: str  # requester_id / dev_owner_id / ui_owner_id / qa_owner_id

    def describe(self) -> str:
        return SLOT_LABELS[self.slot]


ActorClause = RoleClause | SlotClause

SLOT_LABELS: dict[str, str] = {
    "requester_id": "요청자 본인",
    "dev_owner_id": "지정된 개발담당",
    "ui_owner_id": "지정된 UI담당",
    "qa_owner_id": "지정된 검수담당",
}


# ---------------------------------------------------------------------------
# 전이 시점에 수집하는 입력
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Input:
    """전이 다이얼로그에서 받는 입력 한 칸.

    PRD 7.6절: "필수 입력은 전이 시점에 받는다. 승인하려는데 공수가 없다면 그 자리에서
    입력받는다." 따라서 전이 폼은 이 목록만으로 렌더링된다.
    """

    name: str
    label: str
    kind: str  # text | textarea | date | number | select_user | select_choice
    required: bool = True
    #: 값을 기록할 FeatureRequest 컬럼. None이면 전이 이력(payload)에만 남는다.
    target_field: str | None = None
    #: select_user 일 때 후보를 거를 역할
    user_role: Role | None = None
    #: select_choice 일 때 선택지 (코드, 라벨) 목록
    choices: tuple[tuple[str, str], ...] = ()
    help_text: str = ""


def _choices(enum_cls) -> tuple[tuple[str, str], ...]:
    return tuple((member.value, member.label) for member in enum_cls)


# ---------------------------------------------------------------------------
# 알림 대상
# ---------------------------------------------------------------------------

#: 알림 대상 토큰. 실제 사용자 해석은 notifications.resolve_targets 가 담당한다.
NOTIFY_REQUESTER = "REQUESTER"
NOTIFY_DEV_OWNER = "DEV_OWNER"
NOTIFY_UI_OWNER = "UI_OWNER"
NOTIFY_QA_OWNER = "QA_OWNER"
NOTIFY_ALL_OWNERS = "ALL_OWNERS"
NOTIFY_ROLE_DEV = "ROLE_DEV"
NOTIFY_ROLE_UI = "ROLE_UI"
#: 보완요청의 회귀 대상에 해당하는 담당자 (요건->요청자, UI->UI담당, 구현->개발담당)
NOTIFY_REGRESSION_OWNER = "REGRESSION_OWNER"


# ---------------------------------------------------------------------------
# 전이 정의
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Transition:
    """docs/data-model.md 5절 표의 한 행."""

    id: str  # T01 ~ T22
    action: str  # action_code
    label: str  # 버튼에 표시할 한국어 이름
    sources: tuple[Status, ...]  # 빈 튜플이면 생성 전이(T01)
    target: Status
    actors: tuple[ActorClause, ...]
    inputs: tuple[Input, ...] = ()
    #: 전이 전에 FR에 이미 채워져 있어야 하는 컬럼 (FR-102: 제출 시점 검증)
    required_fields: tuple[str, ...] = ()
    notify: tuple[str, ...] = ()
    #: FR에 무조건 적용할 값 (예: T05는 ui_change_required=True 로 확정)
    effects: dict[str, object] = field(default_factory=dict)
    #: 추가 조건. 만족하지 않으면 이 전이는 아예 노출되지 않는다.
    guard: Callable[["FeatureRequest"], bool] | None = None
    #: 확인 다이얼로그가 필요한 되돌릴 수 없는 행동 (PRD 7.6절)
    destructive: bool = False
    note: str = ""

    @property
    def is_creation(self) -> bool:
        return not self.sources

    def missing_inputs(self, values: dict[str, object]) -> list[str]:
        """FR-203: 채워지지 않은 필수 입력의 라벨 목록."""
        missing = []
        for spec in self.inputs:
            if not spec.required:
                continue
            raw = values.get(spec.name)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                missing.append(spec.label)
        return missing

    def missing_fields(self, fr: "FeatureRequest") -> list[str]:
        """전이 전에 FR에 이미 채워져 있어야 하는데 비어 있는 필드의 라벨 목록."""
        from .permissions import FIELD_LABELS

        missing = []
        for name in self.required_fields:
            value = getattr(fr, name, None)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(FIELD_LABELS.get(name, name))
        return missing


def _regression_is(target: RegressionTarget) -> Callable[["FeatureRequest"], bool]:
    """T18~T20 가드: 열린 보완요청의 회귀 대상이 일치할 때만 해당 접수 전이를 연다.

    회귀 대상이 ``DEV`` 인 보완요청을 UI담당이 접수하는 것을 막는다 (E5 시나리오).
    """

    def _guard(fr: "FeatureRequest") -> bool:
        rework = fr.open_rework
        return rework is not None and rework.regression_target == target

    return _guard


#: 취소(T22)가 가능한 진행 상태. docs/data-model.md 5절 T22.
CANCELABLE_STATUSES: tuple[Status, ...] = (
    Status.REVIEW,
    Status.ON_HOLD,
    Status.UI_DESIGN,
    Status.IN_DEV,
    Status.DEV_DONE,
    Status.IN_TEST,
    Status.REWORK,
)

_REWORK_INPUTS: tuple[Input, ...] = (
    Input(
        "regression_target",
        "회귀 대상",
        "select_choice",
        choices=_choices(RegressionTarget),
        help_text="어디로 되돌아가는가. 요건→요건검토, UI→UI설계, 구현→개발중",
    ),
    Input("severity", "심각도", "select_choice", choices=_choices(Severity)),
    Input("reason", "보완 내용", "textarea", help_text="무엇이 왜 보완되어야 하는지"),
)


TRANSITIONS: tuple[Transition, ...] = (
    Transition(
        id="T01",
        action="CREATE",
        label="요구사항 등록",
        sources=(),
        target=Status.DRAFT,
        actors=(RoleClause(Role.BIZ),),
        inputs=(
            Input("title", "제목", "text"),
            Input("description", "상세 내용", "textarea"),
            Input("product", "대상 제품", "text"),
            Input(
                "category",
                "기능 구분",
                "select_choice",
                choices=_choices(Category),
            ),
        ),
        note="생성 즉시 DRAFT. 나머지 항목은 제출 전까지 비워둘 수 있다 (FR-102).",
    ),
    Transition(
        id="T02",
        action="SUBMIT",
        label="검토요청",
        sources=(Status.DRAFT,),
        target=Status.SUBMITTED,
        actors=(SlotClause("requester_id"),),
        required_fields=("priority", "desired_due_date", "acceptance_criteria"),
        notify=(NOTIFY_ROLE_DEV, NOTIFY_ROLE_UI),
        note="FR-102: 제출 시점에 우선순위·희망완료일·완료조건을 검증한다.",
    ),
    Transition(
        id="T03",
        action="START_REVIEW",
        label="검토착수",
        sources=(Status.SUBMITTED,),
        target=Status.REVIEW,
        actors=(RoleClause(Role.DEV), RoleClause(Role.UI)),
        inputs=(
            Input(
                "dev_owner_id",
                "개발담당 지정",
                "select_user",
                user_role=Role.DEV,
                target_field="dev_owner_id",
            ),
        ),
        notify=(NOTIFY_REQUESTER, NOTIFY_DEV_OWNER),
        note="아직 담당자가 없으므로 역할 보유만으로 착수할 수 있다.",
    ),
    Transition(
        id="T04",
        action="RETURN",
        label="정보부족 반환",
        sources=(Status.SUBMITTED,),
        target=Status.DRAFT,
        actors=(RoleClause(Role.DEV), RoleClause(Role.UI)),
        inputs=(Input("comment", "반환 사유", "textarea"),),
        notify=(NOTIFY_REQUESTER,),
    ),
    Transition(
        id="T05",
        action="APPROVE_WITH_UI",
        label="승인 · UI설계 필요",
        sources=(Status.REVIEW,),
        target=Status.UI_DESIGN,
        actors=(SlotClause("dev_owner_id"),),
        inputs=(
            Input("estimate_md", "예상 공수(MD)", "number", target_field="estimate_md"),
            Input(
                "target_due_date",
                "목표 완료일",
                "date",
                target_field="target_due_date",
                help_text="이후 지연 판정의 기준이 된다",
            ),
            Input(
                "ui_owner_id",
                "UI담당 지정",
                "select_user",
                user_role=Role.UI,
                target_field="ui_owner_id",
            ),
            Input(
                "qa_owner_id",
                "검수담당 지정",
                "select_user",
                user_role=Role.QA,
                target_field="qa_owner_id",
            ),
        ),
        effects={"ui_change_required": True},
        notify=(NOTIFY_REQUESTER, NOTIFY_UI_OWNER, NOTIFY_QA_OWNER),
    ),
    Transition(
        id="T06",
        action="APPROVE_NO_UI",
        label="승인 · UI변경 없음",
        sources=(Status.REVIEW,),
        target=Status.IN_DEV,
        actors=(SlotClause("dev_owner_id"),),
        inputs=(
            Input("estimate_md", "예상 공수(MD)", "number", target_field="estimate_md"),
            Input(
                "target_due_date", "목표 완료일", "date", target_field="target_due_date"
            ),
            Input(
                "qa_owner_id",
                "검수담당 지정",
                "select_user",
                user_role=Role.QA,
                target_field="qa_owner_id",
            ),
        ),
        effects={"ui_change_required": False},
        notify=(NOTIFY_REQUESTER, NOTIFY_QA_OWNER),
        note="FR-207: UI 변경이 없는 건은 UI설계 단계를 건너뛴다.",
    ),
    Transition(
        id="T07",
        action="HOLD",
        label="보류",
        sources=(Status.REVIEW,),
        target=Status.ON_HOLD,
        actors=(RoleClause(Role.BIZ), SlotClause("dev_owner_id")),
        inputs=(
            Input("comment", "보류 사유", "textarea"),
            Input("hold_review_date", "재검토 예정일", "date"),
        ),
        notify=(NOTIFY_REQUESTER, NOTIFY_ALL_OWNERS),
    ),
    Transition(
        id="T08",
        action="REJECT",
        label="반려",
        sources=(Status.REVIEW,),
        target=Status.REJECTED,
        actors=(SlotClause("dev_owner_id"),),
        inputs=(Input("comment", "반려 사유", "textarea"),),
        notify=(NOTIFY_REQUESTER,),
        destructive=True,
    ),
    Transition(
        id="T09",
        action="RESUME",
        label="재개",
        sources=(Status.ON_HOLD,),
        target=Status.REVIEW,
        actors=(RoleClause(Role.BIZ),),
        notify=(NOTIFY_ALL_OWNERS,),
    ),
    Transition(
        id="T10",
        action="REOPEN",
        label="반려 번복",
        sources=(Status.REJECTED,),
        target=Status.REVIEW,
        actors=(RoleClause(Role.BIZ),),
        inputs=(Input("comment", "재검토 사유", "textarea"),),
        notify=(NOTIFY_ALL_OWNERS,),
    ),
    Transition(
        id="T11",
        action="UI_DONE",
        label="설계완료",
        sources=(Status.UI_DESIGN,),
        target=Status.IN_DEV,
        actors=(SlotClause("ui_owner_id"),),
        inputs=(
            Input(
                "ui_design_url",
                "설계 산출물 링크",
                "text",
                target_field="ui_design_url",
                help_text="첨부는 Phase 2. MVP에서는 링크로 남긴다",
            ),
        ),
        notify=(NOTIFY_DEV_OWNER, NOTIFY_QA_OWNER),
    ),
    Transition(
        id="T12",
        action="DEV_DONE",
        label="개발완료",
        sources=(Status.IN_DEV,),
        target=Status.DEV_DONE,
        actors=(SlotClause("dev_owner_id"),),
        inputs=(
            Input(
                "dev_result_summary",
                "개발결과 요약",
                "textarea",
                target_field="dev_result_summary",
            ),
            Input("test_env", "검증 환경", "text", target_field="test_env"),
        ),
        notify=(NOTIFY_QA_OWNER, NOTIFY_REQUESTER),
    ),
    Transition(
        id="T13",
        action="START_TEST",
        label="검수착수",
        sources=(Status.DEV_DONE,),
        target=Status.IN_TEST,
        actors=(SlotClause("qa_owner_id"),),
        notify=(NOTIFY_DEV_OWNER,),
    ),
    Transition(
        id="T14",
        action="PASS",
        label="검수통과",
        sources=(Status.IN_TEST,),
        target=Status.DONE,
        actors=(SlotClause("qa_owner_id"),),
        inputs=(
            Input(
                "test_result_summary",
                "검수 결과 요약",
                "textarea",
                target_field="test_result_summary",
            ),
        ),
        notify=(NOTIFY_REQUESTER, NOTIFY_DEV_OWNER, NOTIFY_UI_OWNER),
    ),
    Transition(
        id="T15",
        action="REQUEST_REWORK",
        label="보완요청",
        sources=(Status.IN_TEST,),
        target=Status.REWORK,
        actors=(SlotClause("qa_owner_id"),),
        inputs=_REWORK_INPUTS,
        notify=(NOTIFY_REGRESSION_OWNER, NOTIFY_REQUESTER),
    ),
    Transition(
        id="T16",
        action="REQUEST_REWORK_PRE",
        label="사전확인 보완요청",
        sources=(Status.DEV_DONE,),
        target=Status.REWORK,
        actors=(RoleClause(Role.BIZ), SlotClause("qa_owner_id")),
        inputs=_REWORK_INPUTS,
        notify=(NOTIFY_REGRESSION_OWNER, NOTIFY_QA_OWNER),
    ),
    Transition(
        id="T17",
        action="REQUEST_REWORK_POST",
        label="사후 보완요청",
        sources=(Status.DONE,),
        target=Status.REWORK,
        actors=(RoleClause(Role.BIZ), SlotClause("qa_owner_id")),
        inputs=_REWORK_INPUTS
        + (Input("discovery_context", "발견 경위", "textarea"),),
        notify=(NOTIFY_ALL_OWNERS, NOTIFY_REQUESTER),
        note="FR-304: 완료 후 결함을 시스템 밖에서 처리하지 않게 한다.",
    ),
    Transition(
        id="T18",
        action="ACCEPT_REWORK_REQ",
        label="보완접수 · 요건",
        sources=(Status.REWORK,),
        target=Status.REVIEW,
        actors=(RoleClause(Role.BIZ),),
        guard=_regression_is(RegressionTarget.REQUIREMENT),
        notify=(NOTIFY_DEV_OWNER, NOTIFY_UI_OWNER),
    ),
    Transition(
        id="T19",
        action="ACCEPT_REWORK_UI",
        label="보완접수 · UI",
        sources=(Status.REWORK,),
        target=Status.UI_DESIGN,
        actors=(SlotClause("ui_owner_id"),),
        guard=_regression_is(RegressionTarget.UI),
        notify=(NOTIFY_DEV_OWNER, NOTIFY_QA_OWNER),
    ),
    Transition(
        id="T20",
        action="ACCEPT_REWORK_DEV",
        label="보완접수 · 구현",
        sources=(Status.REWORK,),
        target=Status.IN_DEV,
        actors=(SlotClause("dev_owner_id"),),
        guard=_regression_is(RegressionTarget.DEV),
        notify=(NOTIFY_QA_OWNER,),
    ),
    Transition(
        id="T21",
        action="CANCEL",
        label="취소",
        sources=(Status.DRAFT,),
        target=Status.CANCELED,
        actors=(SlotClause("requester_id"),),
        inputs=(Input("comment", "취소 사유", "textarea"),),
        destructive=True,
    ),
    Transition(
        id="T22",
        action="CANCEL",
        label="취소",
        sources=CANCELABLE_STATUSES,
        target=Status.CANCELED,
        actors=(SlotClause("requester_id"), RoleClause(Role.BIZ)),
        inputs=(Input("comment", "취소 사유", "textarea"),),
        notify=(NOTIFY_ALL_OWNERS,),
        destructive=True,
    ),
)


# ---------------------------------------------------------------------------
# 조회 헬퍼
# ---------------------------------------------------------------------------

BY_ID: dict[str, Transition] = {t.id: t for t in TRANSITIONS}

CREATION_TRANSITION: Transition = next(t for t in TRANSITIONS if t.is_creation)


def find(transition_id: str) -> Transition | None:
    return BY_ID.get(transition_id)


def transitions_from(status: Status) -> tuple[Transition, ...]:
    """해당 상태에서 정의된 모든 전이. 권한·가드는 보지 않는다."""
    return tuple(t for t in TRANSITIONS if status in t.sources)


def is_defined(from_status: Status, to_status: Status) -> bool:
    """FR-201: 매트릭스에 정의된 조합인지. 정의되지 않은 조합은 전부 금지다."""
    return any(
        from_status in t.sources and t.target == to_status for t in TRANSITIONS
    )


# ---------------------------------------------------------------------------
# 권한 판정 (FR-202)
# ---------------------------------------------------------------------------


def satisfies_actor(
    transition: Transition, fr: "FeatureRequest | None", user: "User"
) -> bool:
    """행위자 절 중 하나라도 만족하면 True.

    ADMIN은 모든 전이를 수행할 수 있다. 운영 사고 복구용이며, 이력에는
    ``actor_role=ADMIN`` 으로 남아 일반 전이와 구분된다 (docs/data-model.md 5절 보충 3).
    """
    if user.has_role(Role.ADMIN):
        return True

    for clause in transition.actors:
        if isinstance(clause, RoleClause):
            if user.has_role(clause.role):
                return True
        else:  # SlotClause
            if fr is not None and getattr(fr, clause.slot, None) == user.id:
                return True
    return False


def can_perform(
    transition: Transition, fr: "FeatureRequest | None", user: "User"
) -> bool:
    """이 사용자가 지금 이 FR에서 해당 전이를 수행할 수 있는가."""
    if transition.is_creation:
        return fr is None and satisfies_actor(transition, None, user)

    if fr is None or fr.status not in transition.sources:
        return False
    if not satisfies_actor(transition, fr, user):
        return False
    if transition.guard is not None and not transition.guard(fr):
        return False
    return True


def available_transitions(
    fr: "FeatureRequest", user: "User"
) -> list[Transition]:
    """FR-208 / FR-503의 단일 근거.

    상세 화면의 전이 버튼도, "내 할 일" 큐의 판정도 모두 이 함수 하나에서 나온다.
    큐 판정 기준이 "역할"이 아니라 "지금 수행 가능한 전이가 1개 이상 존재하는가"인
    이유가 여기에 있다 (PRD 7.4절).
    """
    return [t for t in TRANSITIONS if can_perform(t, fr, user)]


def actor_description(transition: Transition) -> str:
    """권한 거부 메시지에 쓸 '누가 할 수 있는가' 설명."""
    return " 또는 ".join(clause.describe() for clause in transition.actors)


# ---------------------------------------------------------------------------
# 매트릭스 자체 검증 (테스트와 기동 시점에서 사용)
# ---------------------------------------------------------------------------


def validate_matrix() -> list[str]:
    """매트릭스의 구조적 결함을 찾아 사람이 읽을 수 있는 목록으로 돌려준다.

    docs/roadmap.md 4.5절의 "상태머신 완전성" 검증을 코드로 옮긴 것이다.
    """
    problems: list[str] = []

    entered: set[Status] = {t.target for t in TRANSITIONS}
    exited: set[Status] = {s for t in TRANSITIONS for s in t.sources}

    for status in Status:
        if status not in entered:
            problems.append(f"{status}: 진입 전이가 없다")
        if status not in exited and status is not Status.CANCELED:
            problems.append(f"{status}: 진출 전이가 없다")

    seen_ids: set[str] = set()
    for t in TRANSITIONS:
        if t.id in seen_ids:
            problems.append(f"{t.id}: 전이 ID가 중복된다")
        seen_ids.add(t.id)
        for spec in t.inputs:
            if spec.kind == "select_choice" and not spec.choices:
                problems.append(f"{t.id}.{spec.name}: select_choice에 선택지가 없다")
            if spec.kind == "select_user" and spec.user_role is None:
                problems.append(f"{t.id}.{spec.name}: select_user에 역할이 없다")
        if not t.actors:
            problems.append(f"{t.id}: 행위자 규칙이 없다")

    return problems
