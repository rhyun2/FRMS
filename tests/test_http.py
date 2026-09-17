"""HTTP 계층 테스트.

FR-403은 "서버에서 검증하며 UI 숨김에 의존하지 않는다"고 요구한다. 화면에 버튼이
없더라도 URL을 직접 호출하면 막혀야 한다. 그것을 여기서 확인한다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import SESSION_USER_KEY
from app.db import get_db
from app.enums import Category, Priority, RegressionTarget, Role, Severity, Status
from app.main import app
from app.models import Base
from app.services import create_feature_request, perform_transition, update_fields

from .conftest import Cast, plus


@pytest.fixture()
def http(monkeypatch):
    """앱 전체를 인메모리 DB에 물린 테스트 클라이언트."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()

    def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    client = TestClient(app, follow_redirects=False)
    try:
        yield client, session
    finally:
        app.dependency_overrides.clear()
        session.close()


def login_as(client: TestClient, user) -> None:
    """실제 로그인 경로를 거쳐 서명된 세션 쿠키를 얻는다."""
    client.cookies.clear()
    resp = client.post("/auth/dev-login", data={"user_id": user.id})
    assert resp.status_code in (302, 303), resp.text


def test_anonymous_is_redirected_to_login(http):
    client, _ = http
    resp = client.get("/board")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_login_and_board(http):
    client, session = http
    cast = Cast(session)
    session.commit()

    login_as(client, cast.qa)
    resp = client.get("/board")
    assert resp.status_code == 200
    assert "진행 현황" in resp.text


def test_non_biz_cannot_open_create_form(http):
    client, session = http
    cast = Cast(session)
    session.commit()

    login_as(client, cast.dev)
    resp = client.get("/fr/new")
    assert resp.status_code == 403
    assert "사업담당" in resp.text


def test_create_requires_all_fields(http):
    client, session = http
    cast = Cast(session)
    session.commit()

    login_as(client, cast.biz)
    resp = client.post("/fr/new", data={"title": "제목만"})
    assert resp.status_code == 400
    assert "필수 항목" in resp.text


def test_full_create_and_view_over_http(http):
    client, session = http
    cast = Cast(session)
    session.commit()

    login_as(client, cast.biz)
    resp = client.post(
        "/fr/new",
        data={
            "title": "원격 롤백",
            "description": "펌웨어 롤백이 필요하다",
            "product": "Gateway",
            "category": Category.NEW_FEATURE.value,
        },
    )
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/fr/FR-")

    detail = client.get(location)
    assert detail.status_code == 200
    assert "원격 롤백" in detail.text
    assert "작성중" in detail.text


def test_forbidden_transition_is_rejected_at_the_url(http):
    """버튼이 안 보이는 것과 실제로 막히는 것은 다르다 (FR-403)."""
    client, session = http
    cast = Cast(session)
    fr = create_feature_request(
        session, actor=cast.biz,
        values={"title": "t", "description": "d", "product": "p",
                "category": Category.NEW_FEATURE.value},
    )
    update_fields(session, fr=fr, actor=cast.biz,
                  values={"priority": Priority.P1.value,
                          "desired_due_date": plus(10),
                          "acceptance_criteria": "조건"})
    perform_transition(session, fr=fr, transition_id="T02", actor=cast.biz, values={})
    perform_transition(session, fr=fr, transition_id="T03", actor=cast.dev,
                       values={"dev_owner_id": cast.dev.id})
    session.commit()

    # UI담당은 승인 권한이 없다. 화면에도 버튼이 없다.
    login_as(client, cast.ui)
    detail = client.get(f"/fr/{fr.fr_key}")
    assert "/transition/T06" not in detail.text

    # 그래도 URL을 직접 호출하면?
    resp = client.post(
        f"/fr/{fr.fr_key}/transition/T06",
        data={"estimate_md": "1", "target_due_date": plus(5),
              "qa_owner_id": cast.qa.id},
    )
    assert resp.status_code == 403
    session.refresh(fr)
    assert fr.status is Status.REVIEW


def test_transition_form_is_forbidden_for_wrong_actor(http):
    client, session = http
    cast = Cast(session)
    fr = create_feature_request(
        session, actor=cast.biz,
        values={"title": "t", "description": "d", "product": "p",
                "category": Category.NEW_FEATURE.value},
    )
    session.commit()

    login_as(client, cast.other_biz)
    resp = client.get(f"/fr/{fr.fr_key}/transition/T02")
    assert resp.status_code == 403


def test_admin_only_routes(http):
    client, session = http
    cast = Cast(session)
    session.commit()

    login_as(client, cast.dev)
    assert client.get("/admin/users").status_code == 403

    client.cookies.clear()
    login_as(client, cast.admin)
    resp = client.get("/admin/users")
    assert resp.status_code == 200
    assert "사용자 · 역할 관리" in resp.text


def test_unknown_fr_returns_404(http):
    client, session = http
    cast = Cast(session)
    session.commit()

    login_as(client, cast.biz)
    resp = client.get("/fr/FR-2026-9999")
    assert resp.status_code == 404


def test_all_main_screens_render(http):
    """보드·큐·목록·상세·알림이 실제 데이터로 렌더된다."""
    client, session = http
    cast = Cast(session)
    fr = create_feature_request(
        session, actor=cast.biz,
        values={"title": "렌더 확인", "description": "d", "product": "p",
                "category": Category.IMPROVEMENT.value},
    )
    update_fields(session, fr=fr, actor=cast.biz,
                  values={"priority": Priority.P0.value,
                          "desired_due_date": plus(3), "acceptance_criteria": "c"})
    perform_transition(session, fr=fr, transition_id="T02", actor=cast.biz, values={})
    perform_transition(session, fr=fr, transition_id="T03", actor=cast.dev,
                       values={"dev_owner_id": cast.dev.id})
    perform_transition(session, fr=fr, transition_id="T06", actor=cast.dev,
                       values={"estimate_md": "2", "target_due_date": plus(-1),
                               "qa_owner_id": cast.qa.id})
    perform_transition(session, fr=fr, transition_id="T12", actor=cast.dev,
                       values={"dev_result_summary": "완료", "test_env": "stg"})
    perform_transition(session, fr=fr, transition_id="T13", actor=cast.qa, values={})
    perform_transition(
        session, fr=fr, transition_id="T15", actor=cast.qa,
        values={"regression_target": RegressionTarget.DEV.value,
                "severity": Severity.MAJOR.value, "reason": "결함 발견"},
    )
    session.commit()

    login_as(client, cast.dev)
    for path in ("/board", "/my-queue", "/list", "/notifications", f"/fr/{fr.fr_key}"):
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.status_code)

    board = client.get("/board").text
    assert "col-rework" in board  # 보완요청 컬럼 강조
    assert "card-overdue" in board  # 지연 카드 표시

    detail = client.get(f"/fr/{fr.fr_key}").text
    assert "보완요청 이력" in detail
    assert "/transition/T20" in detail  # 개발담당에게 보완접수 버튼이 열려 있다

    queue = client.get("/my-queue").text
    assert fr.fr_key in queue


def test_board_filters_are_in_the_url(http):
    """FR-509: 필터 상태가 URL에 있어 공유·북마크가 된다."""
    client, session = http
    cast = Cast(session)
    session.commit()

    login_as(client, cast.biz)
    resp = client.get("/board?show_closed=true&mine=true")
    assert resp.status_code == 200
    assert 'name="show_closed" value="true" checked' in resp.text.replace("  ", " ")
