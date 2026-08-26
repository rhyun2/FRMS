"""도메인 열거형.

문서 기준: docs/data-model.md 3절(상태 정의), 7.1절(필드 사전).
DB와 API는 코드값(대문자 스네이크케이스)만 사용하고, 한국어 표기는 ``label`` 로만 노출한다.
"""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    """기능 요구사항의 진행단계. docs/data-model.md 3절."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVIEW = "REVIEW"
    ON_HOLD = "ON_HOLD"
    REJECTED = "REJECTED"
    UI_DESIGN = "UI_DESIGN"
    IN_DEV = "IN_DEV"
    DEV_DONE = "DEV_DONE"
    IN_TEST = "IN_TEST"
    REWORK = "REWORK"
    DONE = "DONE"
    CANCELED = "CANCELED"

    @property
    def label(self) -> str:
        return STATUS_LABELS[self]

    @property
    def is_terminal(self) -> bool:
        """종결 상태 여부.

        ``DONE`` 과 ``REJECTED`` 는 각각 사후 보완요청(T17)·번복(T10)으로 되살아날 수 있으나,
        진행 중 목록에서는 제외되므로 종결로 본다. 진짜 최종은 ``CANCELED`` 뿐이다.
        """
        return self in TERMINAL_STATUSES


STATUS_LABELS: dict[Status, str] = {
    Status.DRAFT: "작성중",
    Status.SUBMITTED: "접수",
    Status.REVIEW: "요건검토",
    Status.ON_HOLD: "보류",
    Status.REJECTED: "반려",
    Status.UI_DESIGN: "UI설계",
    Status.IN_DEV: "개발중",
    Status.DEV_DONE: "개발완료",
    Status.IN_TEST: "검수중",
    Status.REWORK: "보완요청",
    Status.DONE: "완료",
    Status.CANCELED: "취소",
}

TERMINAL_STATUSES: frozenset[Status] = frozenset(
    {Status.DONE, Status.REJECTED, Status.CANCELED}
)

#: 칸반 보드 컬럼 순서. docs/PRD.md 7.2절.
#: DRAFT는 작성자 본인에게만 별도 섹션으로, 보류/반려/취소는 토글로 표시하므로 여기서 제외한다.
BOARD_COLUMNS: tuple[Status, ...] = (
    Status.SUBMITTED,
    Status.REVIEW,
    Status.UI_DESIGN,
    Status.IN_DEV,
    Status.DEV_DONE,
    Status.IN_TEST,
    Status.REWORK,
    Status.DONE,
)

#: 상세 화면 진행 스테퍼의 단계 순서. docs/PRD.md 7.3절.
STEPPER_STEPS: tuple[Status, ...] = (
    Status.SUBMITTED,
    Status.REVIEW,
    Status.UI_DESIGN,
    Status.IN_DEV,
    Status.DEV_DONE,
    Status.IN_TEST,
    Status.DONE,
)


class Role(StrEnum):
    """사용자 역할. 한 사용자가 여러 역할을 동시에 보유할 수 있다(FR-404)."""

    BIZ = "BIZ"
    DEV = "DEV"
    UI = "UI"
    QA = "QA"
    ADMIN = "ADMIN"

    @property
    def label(self) -> str:
        return ROLE_LABELS[self]


ROLE_LABELS: dict[Role, str] = {
    Role.BIZ: "사업담당",
    Role.DEV: "개발담당",
    Role.UI: "UI담당",
    Role.QA: "검수담당",
    Role.ADMIN: "관리자",
}


class Priority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"

    @property
    def label(self) -> str:
        return PRIORITY_LABELS[self]


PRIORITY_LABELS: dict[Priority, str] = {
    Priority.P0: "긴급",
    Priority.P1: "높음",
    Priority.P2: "보통",
    Priority.P3: "낮음",
}


class Category(StrEnum):
    NEW_FEATURE = "NEW_FEATURE"
    IMPROVEMENT = "IMPROVEMENT"
    DEFECT = "DEFECT"
    OPS_REQUEST = "OPS_REQUEST"

    @property
    def label(self) -> str:
        return CATEGORY_LABELS[self]


CATEGORY_LABELS: dict[Category, str] = {
    Category.NEW_FEATURE: "신규기능",
    Category.IMPROVEMENT: "개선",
    Category.DEFECT: "결함",
    Category.OPS_REQUEST: "운영요청",
}


class RegressionTarget(StrEnum):
    """보완요청이 되돌아갈 지점. 이 시스템의 가장 중요한 단일 필드.

    docs/data-model.md 7.3절 참조. 이 값이 T18~T20 중 어느 접수 전이가 열리는지를 결정한다.
    """

    REQUIREMENT = "REQUIREMENT"
    UI = "UI"
    DEV = "DEV"

    @property
    def label(self) -> str:
        return REGRESSION_TARGET_LABELS[self]

    @property
    def return_status(self) -> Status:
        """이 회귀 대상이 되돌아가는 상태."""
        return REGRESSION_RETURN_STATUS[self]


REGRESSION_TARGET_LABELS: dict[RegressionTarget, str] = {
    RegressionTarget.REQUIREMENT: "요건",
    RegressionTarget.UI: "UI",
    RegressionTarget.DEV: "구현",
}

REGRESSION_RETURN_STATUS: dict[RegressionTarget, Status] = {
    RegressionTarget.REQUIREMENT: Status.REVIEW,
    RegressionTarget.UI: Status.UI_DESIGN,
    RegressionTarget.DEV: Status.IN_DEV,
}


class Severity(StrEnum):
    BLOCKER = "BLOCKER"
    MAJOR = "MAJOR"
    MINOR = "MINOR"

    @property
    def label(self) -> str:
        return SEVERITY_LABELS[self]


SEVERITY_LABELS: dict[Severity, str] = {
    Severity.BLOCKER: "치명",
    Severity.MAJOR: "주요",
    Severity.MINOR: "경미",
}
