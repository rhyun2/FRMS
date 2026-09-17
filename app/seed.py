"""데모 데이터 생성.

    python -m app.seed          # 비어 있을 때만 생성
    python -m app.seed --reset  # 기존 데이터를 지우고 새로 생성

4개 역할의 사용자와, 워크플로 각 단계에 흩어진 요구사항을 만든다. 보드·내 할 일·
보완요청 루프를 바로 눈으로 확인할 수 있게 하는 것이 목적이다.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

from sqlalchemy import select

from .db import SessionLocal, engine, init_db
from .enums import Category, Priority, RegressionTarget, Role, Severity, Status
from .models import Base, User, UserRole
from .services import create_feature_request, perform_transition, update_fields

DEMO_USERS = [
    ("김사업", "biz1@example.com", [Role.BIZ]),
    ("이사업", "biz2@example.com", [Role.BIZ]),
    ("박개발", "dev1@example.com", [Role.DEV]),
    ("최개발", "dev2@example.com", [Role.DEV, Role.QA]),  # 겸직 (FR-404)
    ("정유아이", "ui1@example.com", [Role.UI]),
    ("한검수", "qa1@example.com", [Role.QA]),
    ("운영자", "admin@example.com", [Role.ADMIN, Role.DEV]),
]


def _ensure_users(db) -> dict[str, User]:
    users: dict[str, User] = {}
    for name, email, roles in DEMO_USERS:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                entra_object_id=f"dev:{email.split('@')[0]}",
                email=email,
                display_name=name,
            )
            db.add(user)
            db.flush()
            for role in roles:
                user.roles.append(UserRole(user_id=user.id, role=role))
            db.flush()
        users[name] = user
    return users


def _plus(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def seed(reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(bind=engine)
    init_db()

    db = SessionLocal()
    try:
        existing = db.scalar(select(User))
        if existing is not None and not reset:
            print("이미 데이터가 있습니다. 새로 만들려면 --reset 을 붙이세요.")
            return

        u = _ensure_users(db)
        biz, biz2 = u["김사업"], u["이사업"]
        dev, ui, qa = u["박개발"], u["정유아이"], u["한검수"]

        def new_fr(actor, title, product, category, description, background=""):
            return create_feature_request(
                db,
                actor=actor,
                values={
                    "title": title,
                    "description": description,
                    "background": background,
                    "product": product,
                    "category": category.value,
                },
            )

        def fill_and_submit(fr, actor, *, priority, due_in, criteria):
            update_fields(
                db,
                fr=fr,
                actor=actor,
                values={
                    "priority": priority.value,
                    "desired_due_date": _plus(due_in),
                    "acceptance_criteria": criteria,
                },
            )
            perform_transition(db, fr=fr, transition_id="T02", actor=actor, values={})

        # 1) 작성중 — 아직 제출 전
        new_fr(
            biz,
            "게이트웨이 펌웨어 원격 롤백 기능",
            "IoT Gateway G3",
            Category.NEW_FEATURE,
            "펌웨어 업데이트 실패 시 이전 버전으로 원격 롤백할 수 있어야 한다.",
            "현장 출동 없이 복구할 수 있어야 운영 비용이 줄어든다.",
        )

        # 2) 접수 — 검토 대기
        fr2 = new_fr(
            biz2,
            "디바이스 목록 CSV 내보내기",
            "관리 콘솔",
            Category.IMPROVEMENT,
            "현재 필터 조건이 적용된 디바이스 목록을 CSV로 내려받을 수 있어야 한다.",
        )
        fill_and_submit(
            fr2, biz2, priority=Priority.P2, due_in=30,
            criteria="필터 적용 상태로 내보내기 시 화면과 동일한 행이 CSV에 포함된다.",
        )

        # 3) 요건검토
        fr3 = new_fr(
            biz,
            "센서 임계치 초과 알림 채널 추가",
            "센서 허브 S2",
            Category.NEW_FEATURE,
            "임계치 초과 시 SMS로도 알림을 받을 수 있어야 한다.",
        )
        fill_and_submit(
            fr3, biz, priority=Priority.P1, due_in=21,
            criteria="임계치 초과 발생 후 1분 이내에 등록된 번호로 SMS가 도착한다.",
        )
        perform_transition(
            db, fr=fr3, transition_id="T03", actor=dev,
            values={"dev_owner_id": dev.id},
        )

        # 4) UI설계 — 승인되어 UI담당에게 넘어간 건
        fr4 = new_fr(
            biz,
            "디바이스 상태 대시보드 개편",
            "관리 콘솔",
            Category.IMPROVEMENT,
            "디바이스 상태를 한 화면에서 파악할 수 있도록 대시보드를 개편한다.",
        )
        fill_and_submit(
            fr4, biz, priority=Priority.P1, due_in=28,
            criteria="오프라인 디바이스가 상단에 모여 보이고 30초마다 자동 갱신된다.",
        )
        perform_transition(db, fr=fr4, transition_id="T03", actor=dev,
                           values={"dev_owner_id": dev.id})
        perform_transition(
            db, fr=fr4, transition_id="T05", actor=dev,
            values={
                "estimate_md": "8",
                "target_due_date": _plus(25),
                "ui_owner_id": ui.id,
                "qa_owner_id": qa.id,
            },
        )

        # 5) 개발중 — UI 변경 없이 바로 개발로 (FR-207)
        fr5 = new_fr(
            biz2,
            "MQTT 재연결 백오프 간격 조정",
            "IoT Gateway G3",
            Category.IMPROVEMENT,
            "재연결 시도 간격을 지수 백오프로 바꿔 브로커 부하를 줄인다.",
        )
        fill_and_submit(
            fr5, biz2, priority=Priority.P2, due_in=14,
            criteria="연속 실패 시 재시도 간격이 1s→2s→4s→…→60s 상한으로 증가한다.",
        )
        perform_transition(db, fr=fr5, transition_id="T03", actor=dev,
                           values={"dev_owner_id": dev.id})
        perform_transition(
            db, fr=fr5, transition_id="T06", actor=dev,
            values={"estimate_md": "3", "target_due_date": _plus(10), "qa_owner_id": qa.id},
        )

        # 6) 검수중 — 목표일이 지난 지연 건
        fr6 = new_fr(
            biz,
            "디바이스 그룹 일괄 설정 적용",
            "관리 콘솔",
            Category.NEW_FEATURE,
            "그룹에 속한 디바이스에 설정을 한 번에 적용할 수 있어야 한다.",
        )
        fill_and_submit(
            fr6, biz, priority=Priority.P0, due_in=-2,
            criteria="그룹 내 전 디바이스에 설정이 적용되고 실패 건은 목록으로 표시된다.",
        )
        perform_transition(db, fr=fr6, transition_id="T03", actor=dev,
                           values={"dev_owner_id": dev.id})
        perform_transition(
            db, fr=fr6, transition_id="T06", actor=dev,
            values={"estimate_md": "5", "target_due_date": _plus(-3), "qa_owner_id": qa.id},
        )
        perform_transition(
            db, fr=fr6, transition_id="T12", actor=dev,
            values={"dev_result_summary": "일괄 적용 API와 실패 목록 반환 구현",
                    "test_env": "staging"},
        )
        perform_transition(db, fr=fr6, transition_id="T13", actor=qa, values={})

        # 7) 보완요청 — 구현 회귀. 접수 대기 상태로 남겨 둔다.
        fr7 = new_fr(
            biz,
            "펌웨어 배포 이력 조회",
            "IoT Gateway G3",
            Category.NEW_FEATURE,
            "디바이스별 펌웨어 배포 이력을 조회할 수 있어야 한다.",
        )
        fill_and_submit(
            fr7, biz, priority=Priority.P1, due_in=12,
            criteria="최근 20건의 배포 이력이 시간 역순으로 표시된다.",
        )
        perform_transition(db, fr=fr7, transition_id="T03", actor=dev,
                           values={"dev_owner_id": dev.id})
        perform_transition(
            db, fr=fr7, transition_id="T06", actor=dev,
            values={"estimate_md": "4", "target_due_date": _plus(8), "qa_owner_id": qa.id},
        )
        perform_transition(
            db, fr=fr7, transition_id="T12", actor=dev,
            values={"dev_result_summary": "배포 이력 조회 API 및 화면 구현",
                    "test_env": "staging"},
        )
        perform_transition(db, fr=fr7, transition_id="T13", actor=qa, values={})
        perform_transition(
            db, fr=fr7, transition_id="T15", actor=qa,
            values={
                "regression_target": RegressionTarget.DEV.value,
                "severity": Severity.MAJOR.value,
                "reason": "이력이 시간 역순이 아니라 정순으로 정렬되어 표시됩니다.",
            },
        )

        # 8) 완료 — 보완요청 1회를 거쳐 통과한 건
        fr8 = new_fr(
            biz2,
            "관리 콘솔 세션 만료 시간 연장",
            "관리 콘솔",
            Category.OPS_REQUEST,
            "세션 만료가 너무 짧아 작업 중 로그아웃된다. 8시간으로 연장한다.",
        )
        fill_and_submit(
            fr8, biz2, priority=Priority.P3, due_in=-10,
            criteria="마지막 활동 후 8시간까지 세션이 유지된다.",
        )
        perform_transition(db, fr=fr8, transition_id="T03", actor=dev,
                           values={"dev_owner_id": dev.id})
        perform_transition(
            db, fr=fr8, transition_id="T06", actor=dev,
            values={"estimate_md": "1", "target_due_date": _plus(-12), "qa_owner_id": qa.id},
        )
        perform_transition(
            db, fr=fr8, transition_id="T12", actor=dev,
            values={"dev_result_summary": "세션 타임아웃 설정값 변경", "test_env": "staging"},
        )
        perform_transition(db, fr=fr8, transition_id="T13", actor=qa, values={})
        perform_transition(
            db, fr=fr8, transition_id="T15", actor=qa,
            values={
                "regression_target": RegressionTarget.DEV.value,
                "severity": Severity.MINOR.value,
                "reason": "설정은 반영됐으나 기존 세션에는 적용되지 않습니다.",
            },
        )
        perform_transition(db, fr=fr8, transition_id="T20", actor=dev, values={})
        perform_transition(
            db, fr=fr8, transition_id="T12", actor=dev,
            values={"dev_result_summary": "기존 세션도 갱신되도록 수정", "test_env": "staging"},
        )
        perform_transition(db, fr=fr8, transition_id="T13", actor=qa, values={})
        perform_transition(
            db, fr=fr8, transition_id="T14", actor=qa,
            values={"test_result_summary": "8시간 유지 확인. 기존 세션 갱신도 확인."},
        )

        db.commit()

        total = db.query(User).count()
        print(f"사용자 {total}명, 요구사항 8건을 생성했습니다.")
        print("\n개발용 로그인 계정 (비밀번호 없음, 화면에서 선택):")
        for name, email, roles in DEMO_USERS:
            labels = ", ".join(r.label for r in roles)
            print(f"  - {name:6} {email:22} {labels}")
    finally:
        db.close()


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
