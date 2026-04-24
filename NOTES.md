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
3. No auth — do not expose v1 publicly.

## Perf measurements
N/A v1.

## Next validation step
`pytest -q` must be green after scaffold. Then a manual curl walkthrough of the vertical slice.
