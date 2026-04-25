# NOTES

## Constraint surface
- **Invariants:**
  - `core/` imports no DB or HTTP code.
  - One producing step per artifact (DB unique).
  - `content_hash` and `step_hash` formulas are frozen for v1.
  - Artifact bodies capped at 10MB (Pydantic validator).
- **Perf bounds (baseline / threshold):** chain walk ≤ 64 nodes / ≤ 200ms p95 at v1 scale. Not a tight budget yet; add budget when traffic exists.
- **API contracts:** see `INTEGRATION.md`.
- **Data sensitivity class:** internal. No secrets inlined in artifacts — actor privkey lives in `.env`, never POSTed, never logged.
- **Must NOT break:** the Researka wire contract in `INTEGRATION.md`.
- **Escalation required:** no — local-only.

## Current objective
Ship v1 vertical slice: source → claim → step → chain → challenge → revision → chain (annotated).

## Task mode
invent

## Success condition
`pytest -q` green. `curl` walkthrough of the full vertical slice returns an annotated chain. Researka team can read `INTEGRATION.md` and start wiring without questions.

## Risk tier
medium — greenfield, single-user, reversible.

## Evidence available
repro — user brief + confirmed design choices.

## Likely files
All under `derivation_web/` and `tests/`.

## Change-impact map
- Surfaces touched: whole repo (new project).
- Blast radius: none (nothing imports DW yet).
- Verify: core tests + API integration test covering the full slice.

## Deletion opportunity?
N/A (greenfield). Ongoing: delete any abstraction that isn't earning its line count against v1.

## Branches considered
- (A) React/Next + ORM-heavy — rejected (LOC, lean brief).
- (B) Neo4j + NetworkX — rejected (deferred; recursive CTE covers v1).
- (C) **HTMX + FastAPI + SQLAlchemy + 3-entity schema** — winner.

## Rejected paths
- LLM calls inside DW (brief: passive ledger).
- Object storage / blob server in v1.
- Trust scoring / reputation / federation.
- `target_artifact_id` on the Artifact row (redundant with step edge).

## Winning path
Passive ledger, 3-entity schema, HTMX+Jinja, inline Postgres bodies, backward walk via producer lookup, chain view primary.

## Open risks
1. Sorted-key JSON ≠ RFC 8785 on float edge cases — acceptable for v1 text-heavy payloads; revisit if Researka hashes floats in metadata.
2. Array column `input_artifact_ids` is Postgres-only; SQLite tests skip.
3. ~~No auth — do not expose v1 publicly.~~ **Resolved 2026-04-25** — API-key transport auth shipped; see `DECISIONS.md`.

## Perf measurements
- Auth dep adds 1× SHA-256 + 1× indexed DB lookup per write — sub-millisecond. 61 tests in 1.1s on local Postgres.

## Next validation step
Researka points its client at `https://dw.domlynch.com` with the issued key in `Authorization: Bearer …` and starts POSTing.

---

## Live state (as of 2026-04-25)

| Layer    | Endpoint                                 | Status                  |
|----------|------------------------------------------|-------------------------|
| MacBook  | dev only, gates via `make lint typecheck test` | green                   |
| GitHub   | `DomLynch/Derivation-Web` private        | synced (manual pushes)  |
| VPS      | systemd `derivation-web` → 100.96.74.1:8080  | active                  |
| Public   | `https://dw.domlynch.com` (nginx + Let's Encrypt) | live, HTTPS-only |

**Auth gate** is on `POST /api/{actors,artifacts,steps}`. Reads remain open.

**Blast-fence retained**: uvicorn bound only to Tailscale interface. Nginx is the sole bridge from public to upstream. Direct `:8080` on the public IP is unreachable (TCP timeout, verified).

**Kill switch**: `systemctl stop derivation-web` on VPS; nginx will then return 502 for all routes.

**Cert renewal**: Let's Encrypt auto-renews via the existing `certbot.timer`. Cert expires 2026-07-24.
