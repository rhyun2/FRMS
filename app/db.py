"""데이터베이스 세션.

SQLAlchemy로 추상화해 두었으므로 ``DATABASE_URL`` 만 바꾸면 PostgreSQL로 전환된다.
MVP 단계에서는 ``create_all`` 로 스키마를 만든다. 스키마 변경이 시작되면
Alembic을 도입한다 (PRD 9절 참조).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base

_settings = get_settings()

_connect_args = (
    {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
)

engine: Engine = create_engine(
    _settings.database_url, connect_args=_connect_args, future=True
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """SQLite는 기본적으로 외래키를 강제하지 않는다. 켜 둔다."""
    if _settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
