# Derivation Web

A tamper-evident provenance substrate for AI/human outputs. Every artifact
(source, claim, challenge, revision) is hashed and optionally signed; every
transform is a typed step. The whole graph is replayable from any node.

This is **a library first, an API second, a UI third** — `core/` is a pure
Python module that consumers import directly. The HTTP layer is one
materialization; you can wire your own.

## What it gives you

- **Append-only ledger.** Artifacts and steps are immutable.
- **Cryptographic provenance.** SHA-256 content + step hashes; Ed25519
  signatures (optional, per-actor).
- **Causal chain retrieval.** `GET /api/artifacts/{id}/chain` walks
  backward through both `input_artifact_ids` and `target_artifact_id`
  so a challenge ends at the claim it disputes, not at the evidence
  it cites.
- **Idempotent posts.** Same `(content_hash, actor_id)` returns the
  same artifact. Different actor on the same content gets a distinct,
  attributed row — creator provenance never silently merges.
- **Transport auth.** API-key-gated writes. Reads stay open by default.

## Status

| Slice | State |
|---|---|
| v1 vertical slice (source → claim → step → chain → challenge → revise) | ✅ live at `https://dw.domlynch.com` |
| API-key auth | ✅ |
| Ed25519 step signing (optional, server-verified) | ✅ |
| Audit log + per-request `X-Request-ID` | ✅ |
| Daily off-box backups | ✅ |
| Public access for non-Researka clients | not v1 — Researka is customer zero |

## Read order

1. [`AGENTS.md`](AGENTS.md) — project conventions and non-negotiables.
2. [`INTEGRATION.md`](INTEGRATION.md) — wire contract for clients.
3. [`DECISIONS.md`](DECISIONS.md) — design decisions with reasoning.
4. [`RUNBOOK.md`](RUNBOOK.md) — incident playbooks for the live deploy.

## Run locally

```bash
cp .env.example .env
docker compose up -d db
pip install -e '.[dev]'
alembic upgrade head
uvicorn derivation_web.api.app:app --reload --port 8080
```

## Test

```bash
ruff check . && mypy derivation_web && pytest -q
```

CI runs the same gates on every push and PR. Pre-push hook
(`.githooks/pre-push`) runs them locally too — activate with
`git config core.hooksPath .githooks`.
