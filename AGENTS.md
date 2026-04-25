# AGENTS.md — Derivation Web

## What it is
Provenance substrate for AI/human outputs. Every result becomes an inspectable, hashable, signable chain of sources, transforms, claims, challenges, and revisions.

**DW is a library first, API second, UI third.** Researka is customer zero, not the container.

**Direction (v1, frozen):** Researka is a DW client; DW is the authoritative provenance store. Researka POSTs in; DW never calls out. See `INTEGRATION.md`.

## v1 scope (locked)
One vertical slice end-to-end:
`POST source → POST claim → POST step(summarize) → GET chain → POST challenge → POST revision → GET chain`

### In
- 3-entity domain: `actors`, `artifacts` (kind: `source|claim|challenge|revision`), `steps` (typed edges, one per produced artifact, with explicit `target_artifact_id` for `challenge`/`revise` so evidence inputs are never confused with the targeted claim)
- Content hashing: SHA-256 over sorted-key canonical JSON
- Ed25519 signatures (env-seeded, single keypair per actor)
- Inline Postgres artifact bodies (10MB cap via Pydantic)
- Recursive backward provenance walk via a `produces` index; walks both `input_artifact_ids` (sources/evidence) and `target_artifact_id` (for `challenge`/`revise`)
- Chain view (primary) + node-detail view (secondary). **No graph viz in v1.**
- Researka-compatible actor schema — see `INTEGRATION.md`

### Out (non-goals, v1)
LLM calls, multi-tenant, object storage, NetworkX, trust scoring, reputation, blockchain, federation, React/Next, websockets, export/report, graph viz, bulk APIs, webhooks. **Auth: in-scope as of 2026-04-25** — API-key transport auth on write endpoints. See `INTEGRATION.md` for the header contract.

## Layered architecture
```
core/   # pure Python. no DB, no HTTP. imports: pydantic, cryptography.
db/     # SQLAlchemy 2.0 + Alembic. imports core/.
api/    # FastAPI. imports core/, db/.
web/    # Jinja templates served by api/. imports nothing.
```

**`core/` never imports `db/` or `api/`.** That is the seam Researka will reach through.

## Hashing contract (must stay stable in v1)
- **Canonical JSON:** `json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode("utf-8")`. RFC 8785 adopted when cross-language clients appear; today's payloads are number-light so sorted-key JSON is deterministic enough.
- **Content hash:** `sha256(canonical({kind, content_type, body_text, body_base64, metadata}))` → hex
- **Step hash:** `sha256(canonical({step_type, input_artifact_ids, output_artifact_id, target_artifact_id, actor_id, method, created_at_iso}))` → hex. `target_artifact_id` is `null` for non-annotation steps; it is *always* included in the hash input so clients can pre-compute and sign.
- **Client-supplied `created_at`:** timezone-aware ISO 8601. DW validates clock skew (≤60s into the future) but never overwrites it. This is what makes signatures round-trip.
- **Signature:** Ed25519 over the step hash string. Base64.
- **Input order is semantic** — do not sort `input_artifact_ids` inside DW. Sort at the client if your step type is commutative.

## Non-negotiables
1. `core/` has zero web/db deps.
2. Semantics in explicit columns, not loose JSON. `artifact.kind`, `step.step_type`, `step.input_artifact_ids`, `step.output_artifact_id` are queryable.
3. Chain view is primary; graph view is deferred.
4. One producing step per artifact (DB unique constraint on `steps.output_artifact_id`).
5. Artifacts dedupe on the composite `(content_hash, actor_id)` — same actor re-POSTing the same body returns the same id; a different actor POSTing the same body gets a distinct, attributed artifact. Creator provenance never silently merges.
6. No new dependency without a line in `DECISIONS.md`.

## Run
```
cp .env.example .env
docker compose up -d db
pip install -e '.[dev]'
alembic upgrade head
uvicorn derivation_web.api.app:app --reload --port 8080
```

## Test
```
pytest -q        # core tests always; API tests need DATABASE_URL
```

## Pre-push checks (CI is intentional opt-out)
Run all three before every push. No GitHub Actions; no `.github/workflows/`.
```
ruff check . && mypy derivation_web && pytest -q
```

## Deploy
Runs on VPS Brain (`100.96.74.1:8080`, uvicorn bound to Tailscale interface).
Public reachability: `https://dw.domlynch.com` via nginx + Let's Encrypt
once configured.
- Service: `systemctl {status,restart,stop} derivation-web`
- Pull + restart pattern (as root on VPS):
  `cd /opt/derivation-web && git pull --ff-only && chown -R dw:dw . && chown -R root:root .git && systemctl restart derivation-web`
- Migrations after pull (if migrations changed):
  `set -a; . /etc/derivation-web/env; set +a; /opt/derivation-web/.venv/bin/alembic upgrade head`
- Issue / revoke / list API keys:
  `set -a; . /etc/derivation-web/env; set +a`
  `/opt/derivation-web/.venv/bin/python -m derivation_web.tools.issue_key {issue --client-id <name> | revoke --key-id <id> | list}`
- Kill switch: `systemctl stop derivation-web` (instantly takes service offline; nginx will start returning 502).
