"""Database engine + session factory.

Sync SQLAlchemy 2.0 with psycopg3 driver. Async support can be added in
v0.2 if needed; sync is fine for v0.1's request scale.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from townsquare.db.models import Base
from townsquare.settings import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(settings.db_url, pool_pre_ping=True, future=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context-managed session: commits on success, rolls back on error."""
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables. Idempotent — alpha-only; replace with Alembic in prod."""
    Base.metadata.create_all(get_engine())


def reset_db() -> None:
    """Drop and recreate all tables. DANGEROUS — tests only."""
    Base.metadata.drop_all(get_engine())
    Base.metadata.create_all(get_engine())
