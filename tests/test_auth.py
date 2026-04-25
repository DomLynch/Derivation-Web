"""API-key transport auth: 401s, 201s, header parsing, revocation.

Auth gates the three write endpoints. Reads remain open.
"""

from __future__ import annotations

import hashlib

from derivation_web.api.auth import _extract_key, generate_key, hash_key

_VALID_ACTOR = {"id": "auth:smoke", "kind": "human", "name": "Smoke"}
_VALID_ARTIFACT = {
    "kind": "claim",
    "content_type": "text/plain",
    "body_text": "x",
    "actor_id": "auth:smoke",
}
_VALID_STEP = {
    "step_type": "summarize",
    "input_artifact_ids": ["art_a"],
    "output_artifact_id": "art_b",
    "target_artifact_id": None,
    "actor_id": "auth:smoke",
    "method": {},
    "created_at": "2026-04-25T00:00:00+00:00",
}


# -------- helpers under test --------

def test_generate_key_format():
    raw, kh = generate_key()
    assert raw.startswith("dwk_")
    # 32 random bytes → 43 url-safe base64 chars (no padding)
    assert len(raw) >= 4 + 43
    assert kh == hashlib.sha256(raw.encode()).hexdigest()
    assert len(kh) == 64


def test_generate_key_unique():
    keys = {generate_key()[0] for _ in range(50)}
    assert len(keys) == 50


def test_extract_key_x_api_key_priority():
    # X-API-Key wins if both supplied
    assert _extract_key("Bearer ignored", "from-header") == "from-header"


def test_extract_key_bearer():
    assert _extract_key("Bearer abc123", None) == "abc123"
    assert _extract_key("bearer abc123", None) == "abc123"  # case-insensitive scheme


def test_extract_key_rejects_other_schemes():
    assert _extract_key("Basic abc", None) is None
    assert _extract_key("Token abc", None) is None
    assert _extract_key("abc", None) is None  # no scheme


def test_extract_key_handles_empty():
    assert _extract_key(None, None) is None
    assert _extract_key("", "") is None
    assert _extract_key("Bearer", None) is None  # no key after scheme


# -------- write endpoints: 401 without auth --------

def test_write_actors_requires_key(unauthed_client):
    r = unauthed_client.post("/api/actors", json=_VALID_ACTOR)
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


def test_write_artifacts_requires_key(unauthed_client):
    r = unauthed_client.post("/api/artifacts", json=_VALID_ARTIFACT)
    assert r.status_code == 401


def test_write_steps_requires_key(unauthed_client):
    r = unauthed_client.post("/api/steps", json=_VALID_STEP)
    assert r.status_code == 401


def test_invalid_key_rejected(unauthed_client):
    r = unauthed_client.post(
        "/api/actors",
        json=_VALID_ACTOR,
        headers={"Authorization": "Bearer dwk_definitely_not_real"},
    )
    assert r.status_code == 401
    assert "invalid" in r.json()["detail"].lower()


def test_wrong_scheme_rejected(unauthed_client):
    r = unauthed_client.post(
        "/api/actors",
        json=_VALID_ACTOR,
        headers={"Authorization": "Basic dwk_zzzz"},
    )
    assert r.status_code == 401


def test_empty_bearer_rejected(unauthed_client):
    r = unauthed_client.post(
        "/api/actors",
        json=_VALID_ACTOR,
        headers={"Authorization": "Bearer "},
    )
    assert r.status_code == 401


# -------- write endpoints: 201 with valid key --------

def test_authed_actor_create_succeeds(unauthed_client, issued_key):
    raw, _ = issued_key
    r = unauthed_client.post(
        "/api/actors",
        json=_VALID_ACTOR,
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 201, r.text


def test_x_api_key_header_works(unauthed_client, issued_key):
    raw, _ = issued_key
    r = unauthed_client.post(
        "/api/actors", json=_VALID_ACTOR, headers={"X-API-Key": raw}
    )
    assert r.status_code == 201


def test_lowercase_bearer_works(unauthed_client, issued_key):
    raw, _ = issued_key
    r = unauthed_client.post(
        "/api/actors",
        json=_VALID_ACTOR,
        headers={"Authorization": f"bearer {raw}"},
    )
    assert r.status_code == 201


# -------- revocation --------

def test_revoked_key_rejected(unauthed_client, issued_key):
    raw, key_id = issued_key
    # Sanity: works first
    r = unauthed_client.post(
        "/api/actors",
        json=_VALID_ACTOR,
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 201

    # Revoke
    from derivation_web.db import repo
    from derivation_web.db.session import make_session

    with make_session() as s:
        assert repo.revoke_api_key(s, key_id) is True
        s.commit()

    # Same key now rejected
    r = unauthed_client.post(
        "/api/actors",
        json={**_VALID_ACTOR, "id": "auth:smoke2"},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 401


def test_revoke_idempotent(app, issued_key):
    _, key_id = issued_key
    from derivation_web.db import repo
    from derivation_web.db.session import make_session

    with make_session() as s:
        assert repo.revoke_api_key(s, key_id) is True
        s.commit()
        # Second revoke is a no-op (already revoked)
        assert repo.revoke_api_key(s, key_id) is False


# -------- read endpoints stay open --------

def test_health_open(unauthed_client):
    assert unauthed_client.get("/health").status_code == 200


def test_get_artifact_open_returns_404_not_401(unauthed_client):
    r = unauthed_client.get("/api/artifacts/art_does_not_exist")
    assert r.status_code == 404  # confirms auth dep is NOT on this route


def test_get_chain_open_returns_404_not_401(unauthed_client):
    r = unauthed_client.get("/api/artifacts/art_nope/chain")
    assert r.status_code == 404


def test_index_open(unauthed_client):
    assert unauthed_client.get("/").status_code == 200


# -------- hash storage invariant --------

def test_raw_key_never_in_db(app, issued_key):
    """No table column should contain the raw key text."""
    raw, _ = issued_key
    from sqlalchemy import text

    from derivation_web.db.session import make_session

    with make_session() as s:
        rows = s.execute(text("SELECT id, key_hash, client_id FROM api_keys")).all()
    assert rows, "fixture should have inserted at least one key"
    for row in rows:
        for col in row:
            assert raw not in str(col), "raw key leaked into DB"
    assert any(row.key_hash == hash_key(raw) for row in rows)
