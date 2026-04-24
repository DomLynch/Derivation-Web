"""End-to-end: the full vertical slice + contract regressions through HTTP."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _now() -> str:
    return _iso(datetime.now(UTC))


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_vertical_slice(client):
    r = client.post(
        "/api/actors", json={"id": "local:dev", "kind": "human", "name": "Dev"}
    )
    assert r.status_code == 201, r.text

    src_ids: list[str] = []
    for body in ["paper A content", "paper B content"]:
        r = client.post(
            "/api/artifacts",
            json={
                "kind": "source",
                "content_type": "text/plain",
                "body_text": body,
                "actor_id": "local:dev",
            },
        )
        assert r.status_code == 201, r.text
        src_ids.append(r.json()["id"])

    r = client.post(
        "/api/artifacts",
        json={
            "kind": "claim",
            "content_type": "text/plain",
            "body_text": "Synthesis of A and B shows X.",
            "actor_id": "local:dev",
        },
    )
    assert r.status_code == 201
    claim_id = r.json()["id"]

    r = client.post(
        "/api/steps",
        json={
            "step_type": "summarize",
            "input_artifact_ids": src_ids,
            "output_artifact_id": claim_id,
            "actor_id": "local:dev",
            "method": {"model": "claude-opus-4-7"},
            "created_at": _now(),
        },
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/artifacts/{claim_id}/chain")
    assert r.status_code == 200
    chain = r.json()
    assert chain["root_id"] == claim_id
    ids = [n["artifact"]["id"] for n in chain["nodes"]]
    assert ids[0] == claim_id
    assert set(ids[1:]) == set(src_ids)

    r = client.post(
        "/api/artifacts",
        json={
            "kind": "challenge",
            "content_type": "text/plain",
            "body_text": "Overstates A's evidence.",
            "actor_id": "local:dev",
        },
    )
    assert r.status_code == 201
    ch_id = r.json()["id"]
    r = client.post(
        "/api/steps",
        json={
            "step_type": "challenge",
            "input_artifact_ids": [],
            "output_artifact_id": ch_id,
            "target_artifact_id": claim_id,
            "actor_id": "local:dev",
            "method": {"reason_code": "overstated"},
            "created_at": _now(),
        },
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/artifacts",
        json={
            "kind": "revision",
            "content_type": "text/plain",
            "body_text": "Synthesis of A and B suggests X under conditions Y.",
            "actor_id": "local:dev",
        },
    )
    assert r.status_code == 201
    rev_id = r.json()["id"]
    r = client.post(
        "/api/steps",
        json={
            "step_type": "revise",
            "input_artifact_ids": [ch_id],
            "output_artifact_id": rev_id,
            "target_artifact_id": claim_id,
            "actor_id": "local:dev",
            "method": {"based_on_challenge": ch_id},
            "created_at": _now(),
        },
    )
    assert r.status_code == 201

    r = client.get(f"/api/artifacts/{claim_id}/chain")
    root = r.json()["nodes"][0]
    assert root["artifact"]["id"] == claim_id
    assert len(root["challenges"]) == 1
    assert root["challenges"][0]["artifact"]["id"] == ch_id
    assert len(root["revisions"]) == 1
    assert root["revisions"][0]["artifact"]["id"] == rev_id


def test_artifact_idempotent_per_actor(client):
    """Same actor + same content → same artifact."""
    client.post("/api/actors", json={"id": "a1", "kind": "human", "name": "A"})
    first = client.post(
        "/api/artifacts",
        json={
            "kind": "source",
            "content_type": "text/plain",
            "body_text": "same",
            "actor_id": "a1",
        },
    ).json()
    second = client.post(
        "/api/artifacts",
        json={
            "kind": "source",
            "content_type": "text/plain",
            "body_text": "same",
            "actor_id": "a1",
        },
    ).json()
    assert first["id"] == second["id"]
    assert first["content_hash"] == second["content_hash"]


def test_cross_actor_identical_content_does_not_merge(client):
    """Regression for P1: cross-actor dedupe was silently reattributing authorship."""
    client.post(
        "/api/actors", json={"id": "actor1", "kind": "human", "name": "One"}
    )
    client.post(
        "/api/actors", json={"id": "actor2", "kind": "human", "name": "Two"}
    )
    body = {
        "kind": "source",
        "content_type": "text/plain",
        "body_text": "identical content",
    }
    a1 = client.post("/api/artifacts", json={**body, "actor_id": "actor1"}).json()
    a2 = client.post("/api/artifacts", json={**body, "actor_id": "actor2"}).json()
    assert a1["id"] != a2["id"], "cross-actor submissions must not merge"
    assert a1["actor_id"] == "actor1"
    assert a2["actor_id"] == "actor2"
    assert a1["content_hash"] == a2["content_hash"]  # hash identical, attribution distinct


def test_challenge_evidence_input_is_not_marked_as_challenged(client):
    """Regression for P1: evidence inputs were annotated as if they were the target."""
    client.post("/api/actors", json={"id": "a1", "kind": "human", "name": "A"})
    claim = client.post(
        "/api/artifacts",
        json={
            "kind": "claim",
            "content_type": "text/plain",
            "body_text": "claim",
            "actor_id": "a1",
        },
    ).json()
    evidence = client.post(
        "/api/artifacts",
        json={
            "kind": "source",
            "content_type": "text/plain",
            "body_text": "contradicting evidence",
            "actor_id": "a1",
        },
    ).json()
    ch = client.post(
        "/api/artifacts",
        json={
            "kind": "challenge",
            "content_type": "text/plain",
            "body_text": "this claim is wrong because evidence X",
            "actor_id": "a1",
        },
    ).json()
    r = client.post(
        "/api/steps",
        json={
            "step_type": "challenge",
            "input_artifact_ids": [evidence["id"]],
            "output_artifact_id": ch["id"],
            "target_artifact_id": claim["id"],
            "actor_id": "a1",
            "method": {},
            "created_at": _now(),
        },
    )
    assert r.status_code == 201, r.text

    # The claim IS challenged:
    claim_chain = client.get(f"/api/artifacts/{claim['id']}/chain").json()
    assert claim_chain["nodes"][0]["challenges"][0]["artifact"]["id"] == ch["id"]

    # The evidence is NOT challenged:
    ev_chain = client.get(f"/api/artifacts/{evidence['id']}/chain").json()
    assert ev_chain["nodes"][0]["challenges"] == []
    assert ev_chain["nodes"][0]["revisions"] == []


def test_duplicate_producing_step_rejected(client):
    client.post("/api/actors", json={"id": "a2", "kind": "human", "name": "A"})
    src = client.post(
        "/api/artifacts",
        json={
            "kind": "source",
            "content_type": "text/plain",
            "body_text": "s",
            "actor_id": "a2",
        },
    ).json()
    out = client.post(
        "/api/artifacts",
        json={
            "kind": "claim",
            "content_type": "text/plain",
            "body_text": "c",
            "actor_id": "a2",
        },
    ).json()
    payload = {
        "step_type": "summarize",
        "input_artifact_ids": [src["id"]],
        "output_artifact_id": out["id"],
        "actor_id": "a2",
        "created_at": _now(),
    }
    first = client.post("/api/steps", json=payload)
    assert first.status_code == 201
    second = client.post("/api/steps", json={**payload, "created_at": _now()})
    assert second.status_code == 409


def test_step_created_at_rejects_far_future(client):
    client.post("/api/actors", json={"id": "tz", "kind": "human", "name": "T"})
    src = client.post(
        "/api/artifacts",
        json={
            "kind": "source",
            "content_type": "text/plain",
            "body_text": "s",
            "actor_id": "tz",
        },
    ).json()
    out = client.post(
        "/api/artifacts",
        json={
            "kind": "claim",
            "content_type": "text/plain",
            "body_text": "c",
            "actor_id": "tz",
        },
    ).json()
    far_future = _iso(datetime.now(UTC) + timedelta(minutes=5))
    r = client.post(
        "/api/steps",
        json={
            "step_type": "summarize",
            "input_artifact_ids": [src["id"]],
            "output_artifact_id": out["id"],
            "actor_id": "tz",
            "method": {},
            "created_at": far_future,
        },
    )
    assert r.status_code == 400
    assert "future" in r.text


def test_signed_step_round_trips(client):
    """End-to-end: client signs locally, server verifies. The P1 #2 fix."""
    from derivation_web.core.signing import generate_keypair, sign

    priv, pub = generate_keypair()
    client.post(
        "/api/actors",
        json={
            "id": "signer",
            "kind": "agent",
            "name": "Signer",
            "pubkey_ed25519_b64": pub,
        },
    )
    src = client.post(
        "/api/artifacts",
        json={
            "kind": "source",
            "content_type": "text/plain",
            "body_text": "signed-src",
            "actor_id": "signer",
        },
    ).json()
    out = client.post(
        "/api/artifacts",
        json={
            "kind": "claim",
            "content_type": "text/plain",
            "body_text": "signed-claim",
            "actor_id": "signer",
        },
    ).json()

    created_at = datetime.now(UTC)
    payload = {
        "step_type": "summarize",
        "input_artifact_ids": [src["id"]],
        "output_artifact_id": out["id"],
        "target_artifact_id": None,
        "actor_id": "signer",
        "method": {},
        "created_at": created_at.isoformat(),
    }
    # Client-side step_hash using the published canonicalization rule.
    digest = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    sig = sign(priv, digest)

    r = client.post("/api/steps", json={**payload, "signature_b64": sig})
    assert r.status_code == 201, r.text
    assert r.json()["step_hash"] == digest
    assert r.json()["signature_b64"] == sig


def test_bad_signature_is_rejected(client):
    from derivation_web.core.signing import generate_keypair, sign

    priv, pub = generate_keypair()
    client.post(
        "/api/actors",
        json={
            "id": "signer2",
            "kind": "agent",
            "name": "Signer2",
            "pubkey_ed25519_b64": pub,
        },
    )
    src = client.post(
        "/api/artifacts",
        json={
            "kind": "source",
            "content_type": "text/plain",
            "body_text": "signed-src2",
            "actor_id": "signer2",
        },
    ).json()
    out = client.post(
        "/api/artifacts",
        json={
            "kind": "claim",
            "content_type": "text/plain",
            "body_text": "signed-claim2",
            "actor_id": "signer2",
        },
    ).json()
    bad_sig = sign(priv, "not-the-step-hash")
    r = client.post(
        "/api/steps",
        json={
            "step_type": "summarize",
            "input_artifact_ids": [src["id"]],
            "output_artifact_id": out["id"],
            "actor_id": "signer2",
            "method": {},
            "created_at": _now(),
            "signature_b64": bad_sig,
        },
    )
    assert r.status_code == 400
    assert "signature verification failed" in r.text


def test_artifact_rejects_both_bodies_at_api_layer(client):
    client.post(
        "/api/actors", json={"id": "bad", "kind": "human", "name": "B"}
    )
    r = client.post(
        "/api/artifacts",
        json={
            "kind": "source",
            "content_type": "text/plain",
            "body_text": "t",
            "body_base64": base64.b64encode(b"b").decode(),
            "actor_id": "bad",
        },
    )
    assert r.status_code == 422
    assert "exactly one" in r.text
