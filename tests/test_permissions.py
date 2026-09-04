"""필드 편집 권한과 내 할 일 큐 파생 규칙.

docs/data-model.md 6절 매트릭스가 실제로 강제되는지 확인한다.
"""

from __future__ import annotations

import pytest

from app import workflow
from app.enums import Priority, RegressionTarget, Role, Severity, Status
from app.permissions import (
    PLAN_INFO,
    REQUEST_INFO,
    TEST_INFO,
    UI_INFO,
    can_edit_group,
    editable_groups,
)
from app.services import (
    WorkflowError,
    create_feature_request,
    my_queue,
    perform_transition,
    update_fields,
)

from .conftest import plus


# ---------------------------------------------------------------------------
# 필드 그룹 편집 권한
# ---------------------------------------------------------------------------


def test_requester_can_edit_request_info_in_draft(db, cast, draft_factory):
    fr = draft_factory()
    assert can_edit_group(REQUEST_INFO, fr, cast.biz)
    changed = update_fields(db, fr=fr, actor=cast.biz, values={"title": "새 제목"})
    assert changed == ["제목"]


def test_other_biz_cannot_edit_someone_elses_request(db, cast, draft_factory):
    fr = draft_factory(requester=cast.biz)
    assert not can_edit_group(REQUEST_INFO, fr, cast.other_biz)
    with pytest.raises(WorkflowError) as exc:
        update_fields(db, fr=fr, actor=cast.other_biz, values={"title": "가로채기"})
    assert exc.value.status == 403


def test_dev_cannot_edit_request_info(db, cast, draft_factory):
    fr = draft_factory()
    assert not can_edit_group(REQUEST_INFO, fr, cast.dev)


def test_dev_owner_can_edit_plan_info_in_review(db, cast, submitted_factory):
    fr = submitted_factory()
    perform_transition(db, fr=fr, transition_id="T03", actor=cast.dev,
                       values={"dev_owner_id": cast.dev.id})
    assert can_edit_group(PLAN_INFO, fr, cast.dev)
    changed = update_fields(db, fr=fr, actor=cast.dev, values={"estimate_md": "7.5"})
    assert changed == ["예상 공수(MD)"]
    assert float(fr.estimate_md) == 7.5


def test_non_owner_dev_cannot_edit_plan_info(db, cast, in_dev_factory):
    fr = in_dev_factory()
    assert not can_edit_group(PLAN_INFO, fr, cast.other_dev)


def test_ui_owner_can_edit_ui_info_only_in_ui_stages(db, cast, in_dev_factory):
    fr = in_dev_factory(with_ui=True)
    assert can_edit_group(UI_INFO, fr, cast.ui)  # IN_DEV는 UI 정보 편집 가능 상태
    perform_transition(db, fr=fr, transition_id="T12", actor=cast.dev,
                       values={"dev_result_summary": "완료", "test_env": "staging"})
    assert not can_edit_group(UI_INFO, fr, cast.ui)  # DEV_DONE에서는 불가


def test_qa_owner_can_edit_test_info(db, cast, in_test_factory):
    fr = in_test_factory()
    assert can_edit_group(TEST_INFO, fr, cast.qa)
    assert not can_edit_group(TEST_INFO, fr, cast.dev)


def test_terminal_status_blocks_all_editing(db, cast, in_test_factory):
    fr = in_test_factory()
    perform_transition(db, fr=fr, transition_id="T14", actor=cast.qa,
                       values={"test_result_summary": "통과"})
    assert fr.status is Status.DONE
    assert editable_groups(fr, cast.biz) == []
    assert editable_groups(fr, cast.dev) == []


def test_admin_can_edit_anything(db, cast, in_dev_factory):
    """운영 사고 복구용. 일상 사용을 권장하지 않는다."""
    fr = in_dev_factory()
    assert can_edit_group(REQUEST_INFO, fr, cast.admin)
    changed = update_fields(db, fr=fr, actor=cast.admin, values={"title": "관리자 정정"})
    assert changed == ["제목"]


def test_partial_permission_rejects_whole_update(db, cast, submitted_factory):
    """권한 없는 필드가 섞이면 전체를 거부한다 — 조용히 무시하면 저장됐다고 믿는다."""
    fr = submitted_factory()
    perform_transition(db, fr=fr, transition_id="T03", actor=cast.dev,
                       values={"dev_owner_id": cast.dev.id})
    original = fr.estimate_md

    with pytest.raises(WorkflowError):
        update_fields(db, fr=fr, actor=cast.dev,
                      values={"estimate_md": "9", "title": "제목까지 바꾸기"})

    assert fr.estimate_md == original  # 허용된 필드도 반영되지 않았다


# ---------------------------------------------------------------------------
# 담당자 지정 검증 (FR-204)
# ---------------------------------------------------------------------------


def test_cannot_assign_user_without_the_role(db, cast, submitted_factory):
    fr = submitted_factory()
    with pytest.raises(WorkflowError) as exc:
        perform_transition(db, fr=fr, transition_id="T03", actor=cast.dev,
                           values={"dev_owner_id": cast.ui.id})
    assert "개발담당" in exc.value.message
    assert fr.status is Status.SUBMITTED


def test_cannot_assign_inactive_user(db, cast, submitted_factory):
    cast.dev.is_active = False
    db.flush()
    fr = submitted_factory()
    with pytest.raises(WorkflowError) as exc:
        perform_transition(db, fr=fr, transition_id="T03", actor=cast.admin,
                           values={"dev_owner_id": cast.dev.id})
    assert "비활성" in exc.value.message


# ---------------------------------------------------------------------------
# 내 할 일 큐 (FR-503)
# ---------------------------------------------------------------------------


def test_my_queue_is_derived_from_available_transitions(db, cast, in_test_factory):
    fr = in_test_factory()

    assert fr in my_queue(db, cast.qa)  # 검수담당은 검수통과/보완요청 가능
    assert fr not in my_queue(db, cast.ui)  # UI담당은 지금 할 게 없다
    assert fr not in my_queue(db, cast.other_dev)  # 담당자가 아니다

    for candidate in my_queue(db, cast.qa):
        assert workflow.available_transitions(candidate, cast.qa)


def test_my_queue_excludes_destructive_only_items(db, cast, in_dev_factory):
    """취소만 가능한 건은 큐에 넣지 않는다.

    취소(T22)는 사업담당이면 진행 중 거의 모든 건에 가능하다. 그것까지 세면 큐가
    '취소할 수 있는 건 전부'가 되어 목적을 잃는다.
    """
    fr = in_dev_factory()

    available = {t.id for t in workflow.available_transitions(fr, cast.biz)}
    assert available == {"T22"}  # 요청자에게 취소 권한은 여전히 있고
    assert fr not in my_queue(db, cast.biz)  # 큐에는 뜨지 않는다

    assert fr in my_queue(db, cast.dev)  # 개발담당은 개발완료를 해야 한다


def test_my_queue_sorts_overdue_first(db, cast, submitted_factory):
    """지연 → 우선순위 → 목표 완료일 순 (PRD 7.4절)."""
    late = submitted_factory()
    perform_transition(db, fr=late, transition_id="T03", actor=cast.dev,
                       values={"dev_owner_id": cast.dev.id})
    perform_transition(db, fr=late, transition_id="T06", actor=cast.dev,
                       values={"estimate_md": "1", "target_due_date": plus(-5),
                               "qa_owner_id": cast.qa.id})

    ontime = submitted_factory()
    perform_transition(db, fr=ontime, transition_id="T03", actor=cast.dev,
                       values={"dev_owner_id": cast.dev.id})
    perform_transition(db, fr=ontime, transition_id="T06", actor=cast.dev,
                       values={"estimate_md": "1", "target_due_date": plus(30),
                               "qa_owner_id": cast.qa.id})

    assert late.is_overdue and not ontime.is_overdue
    queue = my_queue(db, cast.dev)
    assert queue.index(late) < queue.index(ontime)


def test_rework_queue_goes_only_to_regression_owner(db, cast, in_test_factory):
    """보완요청은 회귀 대상 담당자의 큐에만 들어간다."""
    fr = in_test_factory(with_ui=True)
    perform_transition(
        db, fr=fr, transition_id="T15", actor=cast.qa,
        values={"regression_target": RegressionTarget.UI.value,
                "severity": Severity.MAJOR.value, "reason": "설계 오류"},
    )

    assert fr in my_queue(db, cast.ui)
    assert fr not in my_queue(db, cast.dev)
    assert fr not in my_queue(db, cast.qa)


# ---------------------------------------------------------------------------
# 알림 (FR-601)
# ---------------------------------------------------------------------------


def test_transition_notifies_targets_but_not_actor(db, cast, in_test_factory):
    from app.models import Notification

    fr = in_test_factory()
    db.query(Notification).delete()
    db.flush()

    perform_transition(
        db, fr=fr, transition_id="T15", actor=cast.qa,
        values={"regression_target": RegressionTarget.DEV.value,
                "severity": Severity.MAJOR.value, "reason": "결함"},
    )

    notified = {n.user_id for n in db.query(Notification).all()}
    assert cast.dev.id in notified  # 회귀 대상 담당자
    assert cast.biz.id in notified  # 요청자
    assert cast.qa.id not in notified  # 행위자 본인에게는 보내지 않는다


# ---------------------------------------------------------------------------
# 채번 (FR-109)
# ---------------------------------------------------------------------------


def test_fr_keys_are_sequential_and_not_reused(db, cast, draft_factory):
    from app.enums import Category

    first = draft_factory()
    second = draft_factory()
    assert first.fr_key.endswith("0001")
    assert second.fr_key.endswith("0002")

    perform_transition(db, fr=second, transition_id="T21", actor=cast.biz,
                       values={"comment": "철회"})
    assert second.status is Status.CANCELED

    third = draft_factory()
    assert third.fr_key.endswith("0003")  # 취소된 번호를 재사용하지 않는다
