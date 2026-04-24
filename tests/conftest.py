"""Test fixtures.

Core tests need nothing. API tests require Postgres via DATABASE_URL (or
TEST_DATABASE_URL); they are skipped if neither is set.
"""

from __future__ import annotations

import os

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
def client(db_engine, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", str(db_engine.url))

    from derivation_web.db import session as s

    s.reset()

    from derivation_web.api.app import create_app

    with TestClient(create_app()) as c:
        yield c

    s.reset()
