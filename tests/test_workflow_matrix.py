"""전이 매트릭스 자체에 대한 테스트.

docs/data-model.md 5절의 표와 코드가 어긋나면 여기서 잡힌다. 매트릭스는 권한·필수입력·
버튼 노출·내 할 일 큐의 단일 근거이므로, 여기가 틀리면 나머지가 전부 틀린다.
"""

from __future__ import annotations

import pytest

from app import workflow
from app.enums import Status, TERMINAL_STATUSES
from app.workflow import RoleClause, SlotClause


def test_matrix_has_no_structural_defects():
    """기동 시점에도 거는 검증 (app/main.py). 여기서는 명시적으로 확인한다."""
    assert workflow.validate_matrix() == []


def test_matrix_has_all_22_documented_transitions():
    ids = [t.id for t in workflow.TRANSITIONS]
    assert ids == [f"T{n:02d}" for n in range(1, 23)]


def test_every_status_has_entry_transition():
    entered = {t.target for t in workflow.TRANSITIONS}
    assert entered == set(Status)


def test_every_status_has_exit_except_canceled():
    """CANCELED만 진짜 최종이다. DONE·REJECTED는 되살아날 수 있다."""
    exited = {s for t in workflow.TRANSITIONS for s in t.sources}
    assert set(Status) - exited == {Status.CANCELED}


def test_done_and_rejected_are_reopenable():
    assert workflow.is_defined(Status.DONE, Status.REWORK)  # T17 사후 보완요청
    assert workflow.is_defined(Status.REJECTED, Status.REVIEW)  # T10 번복


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES, key=str))
def test_terminal_statuses_are_marked(status):
    assert status.is_terminal


def test_undefined_combinations_are_rejected():
    """매트릭스에 없는 조합은 전부 금지 (FR-201)."""
    assert not workflow.is_defined(Status.DRAFT, Status.DONE)
    assert not workflow.is_defined(Status.SUBMITTED, Status.IN_DEV)
    assert not workflow.is_defined(Status.REVIEW, Status.DEV_DONE)
    assert not workflow.is_defined(Status.IN_DEV, Status.DONE)
    assert not workflow.is_defined(Status.CANCELED, Status.DRAFT)


def test_rework_transitions_have_regression_guards():
    """T18~T20은 회귀 대상이 맞을 때만 열린다."""
    for transition_id in ("T18", "T19", "T20"):
        assert workflow.BY_ID[transition_id].guard is not None


def test_rework_creating_transitions_require_regression_target():
    """보완요청을 만드는 모든 전이는 회귀 대상을 필수로 받는다 (FR-301)."""
    creators = [t for t in workflow.TRANSITIONS if t.target is Status.REWORK]
    assert {t.id for t in creators} == {"T15", "T16", "T17"}
    for t in creators:
        required = {spec.name for spec in t.inputs if spec.required}
        assert "regression_target" in required, t.id
        assert "severity" in required, t.id
        assert "reason" in required, t.id


def test_approval_transitions_require_plan_inputs():
    """FR-205: 승인 전이는 공수·목표일·검수담당을 확정한다."""
    for transition_id in ("T05", "T06"):
        t = workflow.BY_ID[transition_id]
        names = {spec.name for spec in t.inputs if spec.required}
        assert {"estimate_md", "target_due_date", "qa_owner_id"} <= names


def test_approval_transitions_set_ui_change_flag():
    """FR-207: 어느 승인 전이를 골랐는지가 UI설계 생략 여부를 확정한다."""
    assert workflow.BY_ID["T05"].effects == {"ui_change_required": True}
    assert workflow.BY_ID["T06"].effects == {"ui_change_required": False}
    assert workflow.BY_ID["T05"].target is Status.UI_DESIGN
    assert workflow.BY_ID["T06"].target is Status.IN_DEV


def test_submit_validates_fields_already_on_the_record():
    """FR-102: 제출 시점 검증 항목."""
    assert set(workflow.BY_ID["T02"].required_fields) == {
        "priority",
        "desired_due_date",
        "acceptance_criteria",
    }


def test_destructive_transitions_are_flagged():
    """PRD 7.6절: 되돌릴 수 없는 행동은 확인을 받는다."""
    destructive = {t.id for t in workflow.TRANSITIONS if t.destructive}
    assert destructive == {"T08", "T21", "T22"}  # 반려, 취소(작성중), 취소(진행중)


def test_owner_slot_transitions_do_not_allow_bare_role_holders():
    """담당자 슬롯만 가진 전이는 역할 보유자 절을 갖지 않는다 (FR-202)."""
    slot_only = ("T02", "T05", "T06", "T08", "T11", "T12", "T13", "T14", "T15",
                 "T19", "T20", "T21")
    for transition_id in slot_only:
        clauses = workflow.BY_ID[transition_id].actors
        assert all(isinstance(c, SlotClause) for c in clauses), transition_id


def test_unassigned_stage_transitions_allow_role_holders():
    """담당자가 아직 없는 단계는 역할 보유만으로 착수할 수 있어야 한다."""
    for transition_id in ("T01", "T03", "T04", "T09", "T10", "T18"):
        clauses = workflow.BY_ID[transition_id].actors
        assert all(isinstance(c, RoleClause) for c in clauses), transition_id


def test_notification_tokens_are_known():
    known = {
        workflow.NOTIFY_REQUESTER,
        workflow.NOTIFY_DEV_OWNER,
        workflow.NOTIFY_UI_OWNER,
        workflow.NOTIFY_QA_OWNER,
        workflow.NOTIFY_ALL_OWNERS,
        workflow.NOTIFY_ROLE_DEV,
        workflow.NOTIFY_ROLE_UI,
        workflow.NOTIFY_REGRESSION_OWNER,
    }
    for t in workflow.TRANSITIONS:
        assert set(t.notify) <= known, t.id


def test_only_one_creation_transition():
    creations = [t for t in workflow.TRANSITIONS if t.is_creation]
    assert len(creations) == 1
    assert creations[0].id == "T01"
