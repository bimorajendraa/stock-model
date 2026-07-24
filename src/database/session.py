"""Database engine/session factory.

Kept separate from settings so tests can construct an engine against a
different URL (e.g. a disposable test database) without touching global
config.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config.settings import get_settings


def make_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().database_url
    return create_engine(url, pool_pre_ping=True, future=True)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_session() -> Iterator[Session]:
    """FastAPI-style dependency yielding a request-scoped session."""
    global _engine, _SessionLocal
    if _engine is None:
        _engine = make_engine()
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
