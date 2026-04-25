"""Engine + sessionmaker. Module-level singleton, resettable for tests."""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return url


def _ensure() -> None:
    global _engine, _session_factory
    if _engine is None:
        _engine = create_engine(_database_url(), future=True, pool_pre_ping=True)
        _session_factory = sessionmaker(
            bind=_engine, class_=Session, expire_on_commit=False
        )


def reset() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def get_session() -> Generator[Session, None, None]:
    _ensure()
    assert _session_factory is not None
    with _session_factory() as session:
        yield session


def make_session() -> Session:
    """Return a single Session for non-FastAPI callers (CLI, test setup).

    Caller is responsible for closing it (use as a context manager).
    """
    _ensure()
    assert _session_factory is not None
    return _session_factory()
