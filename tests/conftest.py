"""테스트 공통 픽스처.

각 테스트는 인메모리 SQLite를 새로 받는다. 테스트 간 상태가 새지 않아야
전이 시나리오를 신뢰할 수 있다.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.enums import Category, Priority, Role
from app.models import Base, User, UserRole
from app.services import create_feature_request, perform_transition, update_fields


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


def make_user(db: Session, name: str, *roles: Role) -> User:
    user = User(
        entra_object_id=f"test:{name}",
        email=f"{name}@example.com",
        display_name=name,
    )
    db.add(user)
    db.flush()
    for role in roles:
        user.roles.append(UserRole(user_id=user.id, role=role))
    db.flush()
    return user


class Cast:
    """테스트에 등장하는 배역. 이름으로 부르면 읽기 쉬워진다."""

    def __init__(self, db: Session):
        self.biz = make_user(db, "biz", Role.BIZ)
        self.other_biz = make_user(db, "other_biz", Role.BIZ)
        self.dev = make_user(db, "dev", Role.DEV)
        self.other_dev = make_user(db, "other_dev", Role.DEV)
        self.ui = make_user(db, "ui", Role.UI)
        self.qa = make_user(db, "qa", Role.QA)
        self.admin = make_user(db, "admin", Role.ADMIN)


@pytest.fixture()
def cast(db: Session) -> Cast:
    return Cast(db)


def plus(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


@pytest.fixture()
def draft_factory(db: Session, cast: Cast):
    """DRAFT 상태의 FR을 만든다."""

    def _make(*, requester: User | None = None, title: str = "테스트 요구사항"):
        return create_feature_request(
            db,
            actor=requester or cast.biz,
            values={
                "title": title,
                "description": "상세 내용",
                "product": "IoT Gateway",
                "category": Category.NEW_FEATURE.value,
            },
        )

    return _make


@pytest.fixture()
def submitted_factory(db: Session, cast: Cast, draft_factory):
    """제출(SUBMITTED)까지 진행된 FR."""

    def _make(*, requester: User | None = None):
        actor = requester or cast.biz
        fr = draft_factory(requester=actor)
        update_fields(
            db,
            fr=fr,
            actor=actor,
            values={
                "priority": Priority.P1.value,
                "desired_due_date": plus(20),
                "acceptance_criteria": "완료 조건",
            },
        )
        perform_transition(db, fr=fr, transition_id="T02", actor=actor, values={})
        return fr

    return _make


@pytest.fixture()
def in_dev_factory(db: Session, cast: Cast, submitted_factory):
    """개발중(IN_DEV)까지 진행된 FR. ``with_ui`` 로 UI설계 경유 여부를 고른다."""

    def _make(*, with_ui: bool = False):
        fr = submitted_factory()
        perform_transition(
            db, fr=fr, transition_id="T03", actor=cast.dev,
            values={"dev_owner_id": cast.dev.id},
        )
        if with_ui:
            perform_transition(
                db, fr=fr, transition_id="T05", actor=cast.dev,
                values={
                    "estimate_md": "5",
                    "target_due_date": plus(15),
                    "ui_owner_id": cast.ui.id,
                    "qa_owner_id": cast.qa.id,
                },
            )
            perform_transition(
                db, fr=fr, transition_id="T11", actor=cast.ui,
                values={"ui_design_url": "https://design.example.com/1"},
            )
        else:
            perform_transition(
                db, fr=fr, transition_id="T06", actor=cast.dev,
                values={
                    "estimate_md": "3",
                    "target_due_date": plus(10),
                    "qa_owner_id": cast.qa.id,
                },
            )
        return fr

    return _make


@pytest.fixture()
def in_test_factory(db: Session, cast: Cast, in_dev_factory):
    """검수중(IN_TEST)까지 진행된 FR."""

    def _make(*, with_ui: bool = False):
        fr = in_dev_factory(with_ui=with_ui)
        perform_transition(
            db, fr=fr, transition_id="T12", actor=cast.dev,
            values={"dev_result_summary": "구현 완료", "test_env": "staging"},
        )
        perform_transition(db, fr=fr, transition_id="T13", actor=cast.qa, values={})
        return fr

    return _make
