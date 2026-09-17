"""docs/roadmap.md 4.5절의 필수 E2E 시나리오 8종.

E5~E8은 **거부되는 것이 정답인 테스트**다. 이 네 건이 통과하지 못하면 이 제품은
PRD 2절의 P2(책임 소재가 흐릿하다)·P4(요건이 조용히 바뀐다)를 해결하지 못한다.
"""

from __future__ import annotations

import pytest

from app import workflow
from app.enums import RegressionTarget, Role, Severity, Status
from app.services import WorkflowError, perform_transition, update_fields

from .conftest import plus


# ---------------------------------------------------------------------------
# E1 — 정상 경로 (UI 변경 있음)
# ---------------------------------------------------------------------------


def test_e1_full_path_with_ui(db, cast, submitted_factory):
    fr = submitted_factory()
    assert fr.status is Status.SUBMITTED
    assert fr.submitted_at is not None

    perform_transition(db, fr=fr, transition_id="T03", actor=cast.dev,
                       values={"dev_owner_id": cast.dev.id})
    assert fr.status is Status.REVIEW
    assert fr.dev_owner_id == cast.dev.id

    perform_transition(
        db, fr=fr, transition_id="T05", actor=cast.dev,
        values={"estimate_md": "5", "target_due_date": plus(15),
                "ui_owner_id": cast.ui.id, "qa_owner_id": cast.qa.id},
    )
    assert fr.status is Status.UI_DESIGN
    assert fr.ui_change_required is True
    assert fr.approved_at is not None
    assert float(fr.estimate_md) == 5.0

    perform_transition(db, fr=fr, transition_id="T11", actor=cast.ui,
                       values={"ui_design_url": "https://design.example.com/1"})
    assert fr.status is Status.IN_DEV

    perform_transition(db, fr=fr, transition_id="T12", actor=cast.dev,
                       values={"dev_result_summary": "완료", "test_env": "staging"})
    assert fr.status is Status.DEV_DONE
    assert fr.dev_done_at is not None

    perform_transition(db, fr=fr, transition_id="T13", actor=cast.qa, values={})
    assert fr.status is Status.IN_TEST

    perform_transition(db, fr=fr, transition_id="T14", actor=cast.qa,
                       values={"test_result_summary": "통과"})
    assert fr.status is Status.DONE
    assert fr.done_at is not None
    assert fr.rework_count == 0

    # 전 단계가 이력으로 남는다 (FR-701)
    assert [t.transition_id for t in fr.transitions] == [
        "T01", "T02", "T03", "T05", "T11", "T12", "T13", "T14"
    ]


# ---------------------------------------------------------------------------
# E2 — UI 변경이 없으면 UI설계를 건너뛴다 (FR-207)
# ---------------------------------------------------------------------------


def test_e2_skips_ui_design_when_not_needed(db, cast, submitted_factory):
    fr = submitted_factory()
    perform_transition(db, fr=fr, transition_id="T03", actor=cast.dev,
                       values={"dev_owner_id": cast.dev.id})

    perform_transition(
        db, fr=fr, transition_id="T06", actor=cast.dev,
        values={"estimate_md": "3", "target_due_date": plus(10),
                "qa_owner_id": cast.qa.id},
    )

    assert fr.status is Status.IN_DEV  # UI_DESIGN을 거치지 않았다
    assert fr.ui_change_required is False
    assert Status.UI_DESIGN not in [t.to_status for t in fr.transitions]


# ---------------------------------------------------------------------------
# E3 — 보완요청 루프 (구현 회귀)
# ---------------------------------------------------------------------------


def test_e3_rework_loop_dev_regression(db, cast, in_test_factory):
    fr = in_test_factory()

    perform_transition(
        db, fr=fr, transition_id="T15", actor=cast.qa,
        values={"regression_target": RegressionTarget.DEV.value,
                "severity": Severity.MAJOR.value,
                "reason": "정렬 순서가 반대입니다."},
    )
    assert fr.status is Status.REWORK
    assert fr.rework_count == 1  # FR-303
    rework = fr.open_rework
    assert rework is not None
    assert rework.regression_target is RegressionTarget.DEV
    assert rework.sequence_no == 1
    assert rework.accepted_at is None

    # 개발담당이 접수하면 개발중으로 되돌아간다
    perform_transition(db, fr=fr, transition_id="T20", actor=cast.dev, values={})
    assert fr.status is Status.IN_DEV
    assert fr.reworks[0].accepted_at is not None
    assert fr.reworks[0].accepted_by_id == cast.dev.id
    assert fr.open_rework is None

    # 재개발 후 다시 검수를 거쳐 완료
    perform_transition(db, fr=fr, transition_id="T12", actor=cast.dev,
                       values={"dev_result_summary": "정렬 수정", "test_env": "staging"})
    perform_transition(db, fr=fr, transition_id="T13", actor=cast.qa, values={})
    perform_transition(db, fr=fr, transition_id="T14", actor=cast.qa,
                       values={"test_result_summary": "확인"})

    assert fr.status is Status.DONE
    assert fr.rework_count == 1  # 첫 검수 통과가 아니었음이 남는다


# ---------------------------------------------------------------------------
# E4 — 보완요청 루프 (요건 회귀)
# ---------------------------------------------------------------------------


def test_e4_rework_loop_requirement_regression(db, cast, in_test_factory):
    fr = in_test_factory()

    perform_transition(
        db, fr=fr, transition_id="T15", actor=cast.qa,
        values={"regression_target": RegressionTarget.REQUIREMENT.value,
                "severity": Severity.BLOCKER.value,
                "reason": "완료 조건 자체가 현업 요구와 다릅니다."},
    )
    assert fr.status is Status.REWORK
    assert fr.open_rework.regression_target is RegressionTarget.REQUIREMENT

    # 요건 회귀이므로 사업담당이 접수하고 요건검토로 되돌아간다
    perform_transition(db, fr=fr, transition_id="T18", actor=cast.biz, values={})
    assert fr.status is Status.REVIEW


@pytest.mark.parametrize(
    "target,transition_id,expected",
    [
        (RegressionTarget.REQUIREMENT, "T18", Status.REVIEW),
        (RegressionTarget.UI, "T19", Status.UI_DESIGN),
        (RegressionTarget.DEV, "T20", Status.IN_DEV),
    ],
)
def test_rework_routes_to_declared_target(
    db, cast, in_test_factory, target, transition_id, expected
):
    """회귀 대상이 되돌아갈 단계를 결정한다 — 세 경우 모두."""
    fr = in_test_factory(with_ui=True)
    perform_transition(
        db, fr=fr, transition_id="T15", actor=cast.qa,
        values={"regression_target": target.value,
                "severity": Severity.MINOR.value, "reason": "보완 필요"},
    )
    actor = {"T18": cast.biz, "T19": cast.ui, "T20": cast.dev}[transition_id]
    perform_transition(db, fr=fr, transition_id=transition_id, actor=actor, values={})
    assert fr.status is expected


# ---------------------------------------------------------------------------
# E5 — 회귀 대상이 아닌 담당자의 접수는 거부된다  (거부가 정답)
# ---------------------------------------------------------------------------


def test_e5_wrong_owner_cannot_accept_rework(db, cast, in_test_factory):
    fr = in_test_factory(with_ui=True)
    perform_transition(
        db, fr=fr, transition_id="T15", actor=cast.qa,
        values={"regression_target": RegressionTarget.DEV.value,
                "severity": Severity.MAJOR.value, "reason": "구현 결함"},
    )

    # 회귀 대상이 DEV인데 UI담당이 접수를 시도한다
    with pytest.raises(WorkflowError) as exc:
        perform_transition(db, fr=fr, transition_id="T19", actor=cast.ui, values={})
    assert exc.value.status == 403
    assert fr.status is Status.REWORK  # 상태가 바뀌지 않았다

    # 화면에도 그 버튼이 노출되지 않는다 (FR-208)
    ui_actions = {t.id for t in workflow.available_transitions(fr, cast.ui)}
    assert "T19" not in ui_actions
    dev_actions = {t.id for t in workflow.available_transitions(fr, cast.dev)}
    assert "T20" in dev_actions


# ---------------------------------------------------------------------------
# E6 — 역할만 보유한 제3자는 전이할 수 없다 (FR-202)  (거부가 정답)
# ---------------------------------------------------------------------------


def test_e6_non_assigned_owner_cannot_transition(db, cast, in_dev_factory):
    fr = in_dev_factory()
    assert fr.dev_owner_id == cast.dev.id

    # other_dev 는 DEV 역할을 갖고 있지만 이 FR의 담당자가 아니다
    with pytest.raises(WorkflowError) as exc:
        perform_transition(
            db, fr=fr, transition_id="T12", actor=cast.other_dev,
            values={"dev_result_summary": "임의 완료", "test_env": "x"},
        )
    assert exc.value.status == 403
    assert fr.status is Status.IN_DEV

    assert workflow.available_transitions(fr, cast.other_dev) == []
    # 지정된 개발담당에게는 개발완료만 열린다. 취소(T22)는 요청자·사업담당의 권한이다.
    assert {t.id for t in workflow.available_transitions(fr, cast.dev)} == {"T12"}
    assert "T22" in {t.id for t in workflow.available_transitions(fr, cast.biz)}


def test_e6b_non_requester_cannot_submit(db, cast, draft_factory):
    """다른 사업담당이 남의 초안을 제출할 수 없다."""
    fr = draft_factory(requester=cast.biz)
    update_fields(db, fr=fr, actor=cast.biz,
                  values={"priority": "P1", "desired_due_date": plus(10),
                          "acceptance_criteria": "조건"})

    with pytest.raises(WorkflowError) as exc:
        perform_transition(db, fr=fr, transition_id="T02", actor=cast.other_biz, values={})
    assert exc.value.status == 403
    assert fr.status is Status.DRAFT


# ---------------------------------------------------------------------------
# E7 — 필수 입력 없는 승인은 거부된다 (FR-203)  (거부가 정답)
# ---------------------------------------------------------------------------


def test_e7_approve_without_required_inputs_is_rejected(db, cast, submitted_factory):
    fr = submitted_factory()
    perform_transition(db, fr=fr, transition_id="T03", actor=cast.dev,
                       values={"dev_owner_id": cast.dev.id})

    with pytest.raises(WorkflowError) as exc:
        perform_transition(db, fr=fr, transition_id="T06", actor=cast.dev, values={})

    assert exc.value.status == 400
    assert "예상 공수(MD)" in exc.value.message
    assert "목표 완료일" in exc.value.message
    assert "검수담당 지정" in exc.value.message
    assert fr.status is Status.REVIEW


def test_e7b_submit_without_acceptance_criteria_is_rejected(db, cast, draft_factory):
    """FR-102: 제출 시점에 완료조건·우선순위·희망완료일을 검증한다."""
    fr = draft_factory()

    with pytest.raises(WorkflowError) as exc:
        perform_transition(db, fr=fr, transition_id="T02", actor=cast.biz, values={})

    assert "완료 조건" in exc.value.message
    assert "우선순위" in exc.value.message
    assert fr.status is Status.DRAFT


# ---------------------------------------------------------------------------
# E8 — 승인 이후 요청 정보 직접 수정은 거부된다 (FR-103)  (거부가 정답)
# ---------------------------------------------------------------------------


def test_e8_requester_cannot_edit_request_info_after_approval(db, cast, in_dev_factory):
    """PRD 문제 P4 — '요건이 조용히 바뀐다'를 막는 핵심 제약."""
    fr = in_dev_factory()
    original = fr.description

    with pytest.raises(WorkflowError) as exc:
        update_fields(db, fr=fr, actor=cast.biz,
                      values={"description": "몰래 바꾼 요건"})

    assert exc.value.status == 403
    assert "보완요청" in exc.value.message  # 무엇을 해야 하는지 알려준다
    assert fr.description == original


def test_e8b_requirement_rework_reopens_editing(db, cast, in_test_factory):
    """단, 요건 회귀 보완요청을 거치면 다시 수정할 수 있다."""
    fr = in_test_factory()
    perform_transition(
        db, fr=fr, transition_id="T15", actor=cast.qa,
        values={"regression_target": RegressionTarget.REQUIREMENT.value,
                "severity": Severity.BLOCKER.value, "reason": "요건 오류"},
    )

    changed = update_fields(db, fr=fr, actor=cast.biz,
                            values={"description": "정정된 요건"})

    assert changed == ["상세 내용"]
    assert fr.description == "정정된 요건"
    # 변경이 이력에 남는다 (FR-702)
    assert any(c.field_name == "description" for c in fr.field_changes)


def test_e8c_dev_rework_does_not_reopen_request_editing(db, cast, in_test_factory):
    """구현 회귀에서는 요청 정보를 열어 주지 않는다."""
    fr = in_test_factory()
    perform_transition(
        db, fr=fr, transition_id="T15", actor=cast.qa,
        values={"regression_target": RegressionTarget.DEV.value,
                "severity": Severity.MAJOR.value, "reason": "구현 결함"},
    )

    with pytest.raises(WorkflowError):
        update_fields(db, fr=fr, actor=cast.biz, values={"description": "바꿔보기"})
