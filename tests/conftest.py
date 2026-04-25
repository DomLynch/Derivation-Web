"""Test fixtures.

Core tests need nothing. API tests require Postgres via DATABASE_URL (or
TEST_DATABASE_URL); they are skipped if neither is set.

Fixture stack:
    db_url ─▶ db_engine ─▶ app ─▶ issued_key ─▶ client (authed)
                                          └──▶ unauthed_client
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from derivation_web.db.schema import Base


def _test_db_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest.fixture(scope="session")
def db_url() -> str:
    url = _test_db_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL / DATABASE_URL not set; skipping DB tests")
    if "postgresql" not in url:
        pytest.skip("DW db tests require Postgres (ARRAY column)")
    return url


@pytest.fixture()
def db_engine(db_url):
    engine = create_engine(db_url, future=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_steps_input_ids_gin "
                "ON steps USING gin (input_artifact_ids)"
            )
        )
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def app(db_engine, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", str(db_engine.url))
    from derivation_web.db import session as s

    s.reset()

    from derivation_web.api.app import create_app

    yield create_app()
    s.reset()


@pytest.fixture()
def issued_key(app):
    """Returns (raw_key, key_id). The key is stored only as a hash in DB."""
    from derivation_web.api.auth import generate_key
    from derivation_web.db import repo
    from derivation_web.db.session import make_session

    raw, key_hash = generate_key()
    key_id = f"key_{uuid.uuid4().hex[:12]}"
    with make_session() as session:
        repo.create_api_key(
            session, key_id=key_id, key_hash=key_hash, client_id="testclient"
        )
        session.commit()
    return raw, key_id


@pytest.fixture()
def client(app, issued_key):
    """Authed TestClient — sends Authorization: Bearer <key> by default."""
    from fastapi.testclient import TestClient

    raw, _ = issued_key
    with TestClient(app, headers={"Authorization": f"Bearer {raw}"}) as c:
        yield c


@pytest.fixture()
def unauthed_client(app):
    """TestClient without auth header. For 401 / open-endpoint tests."""
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
