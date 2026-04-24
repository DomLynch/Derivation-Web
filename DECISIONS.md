# DECISION JOURNAL

## 2026-04-24 — Passive ledger, not active executor
**Decision:** DW never calls an LLM. Clients POST pre-computed derivations.
**Why:** Keeps DW deterministic, dependency-free, and matches "Researka is customer zero." Moves LLM-shaped risk into the consumer.
**Alternatives rejected:**
- Reference `summarize` endpoint that calls Claude — rejected: adds API-key + cost surface, blurs the substrate/consumer line.
**Revisit if:** a standalone demo needs to exist before Researka ships.

## 2026-04-24 — 3-entity schema with strict typed columns
**Decision:** `actors`, `artifacts` (with `kind` enum), `steps` (with `step_type` enum + `input_artifact_ids` ARRAY + unique `output_artifact_id`). No `target_artifact_id` on artifact rows.
**Why:** Collapses 5 brief-entities to 3 without losing semantics. Challenge and revision edges live on the step, not duplicated on the artifact. Kind/type are queryable columns, not loose JSON.
**Alternatives rejected:**
- 5 tables per original brief — more tables, more joins, same expressive power.
- JSON blob for `metadata` including target ids — hidden semantics, per feedback: "links must not disappear into vague JSON."
**Revisit if:** query load demands denormalization.

## 2026-04-24 — HTMX + Jinja, not React/Next
**Decision:** Server-rendered HTMX pages with one CDN script tag.
**Why:** Minimum LOC for v1 goal (inspect a chain). React/Next adds ~2k LOC of scaffolding for a list view.
**Alternatives rejected:** React + cytoscape graph (cost not earned; graph is deferred).
**Revisit if:** interactive graph editing becomes a real requirement.

## 2026-04-24 — Chain view primary, graph view deferred
**Decision:** Ship a linear/tree chain list. No graph visualization in v1.
**Why:** Audit is linear. Graph prettiness isn't the product.
**Revisit if:** users demand visual topology after chain view is live.

## 2026-04-24 — Sorted-key JSON for canonical hashing
**Decision:** `json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=False)` for canonicalization in v1. No `rfc8785` dep.
**Why:** Zero new dependency. Deterministic for number-light payloads. Researka is Python, so float-edge-case cross-runtime divergence is not a v1 concern.
**Alternatives rejected:** `rfc8785` package — adds a dep we don't yet need.
**Revisit if:** non-Python clients consume the ledger, or metadata starts carrying floats.

## 2026-04-24 — Ed25519 signatures from day 1, no PKI
**Decision:** One privkey per actor, base64 in env. Sign the step hash string.
**Why:** Cryptographic provenance is the product. Day-1 cost is ~40 LOC. PKI/JWKS is theater at v1.
**Revisit if:** multiple keys per actor / rotation / revocation are needed.

## 2026-04-24 — Inline artifact bodies in Postgres
**Decision:** `body_text` (TEXT) or `body_base64` (TEXT) on the artifact row. Hard cap 10MB.
**Why:** No S3/object-store overhead. Fits v1 workloads (memos, summaries, paper abstracts).
**Revisit if:** Researka needs to register large PDFs as sources.

## 2026-04-24 — Recursive walk via producer lookup, not SQL CTE
**Decision:** Core ships a pure-Python backward walk. `repo.get_producing_step(id)` is the adjacency primitive.
**Why:** Keeps graph logic in `core/` (importable by Researka). SQL CTE was the other candidate; same result, more DB-coupled. Per-node annotation query stays in `repo`.
**Revisit if:** chains grow past O(hundreds) of nodes — one CTE round-trip beats N lookups.

## 2026-04-24 — Library-first repo shape, extractable later
**Decision:** `derivation_web/core` is a zero-web-deps Python package. Researka imports it directly during the coupling phase; DW API is optional.
**Why:** Per the brief: "Core must stay importable without web/db baggage."
**Revisit:** never for v1. This is the architectural non-negotiable.

## 2026-04-24 — Dedupe scoped to (content_hash, actor_id), not content_hash alone
**Decision:** Drop the single-column unique constraint on `artifacts.content_hash`. Add composite unique `(content_hash, actor_id)`. Same actor POSTing same content twice → idempotent; different actor → new attributed row.
**Why:** Independent review flagged that content-only dedupe silently reattributes authorship. For a provenance system that is a contract break. Attribution must never be merged without the authoring actor's consent.
**Alternatives rejected:**
- No dedupe at all — loses retry-idempotency that Researka benefits from.
- Merge with `actor_ids: []` list — adds history surface area, still ambiguous.
**Revisit if:** a use case appears where two actors explicitly want to co-attribute identical content.

## 2026-04-24 — Explicit `steps.target_artifact_id`; inputs are evidence only
**Decision:** Add `target_artifact_id` column on steps (nullable). Required for `challenge` and `revise` step types, forbidden otherwise. `input_artifact_ids` carries evidence only for annotation steps. `get_annotations` queries on `target_artifact_id`, not array-containment over inputs.
**Why:** Reviewers demonstrated that the prior design conflated evidence with target — a challenge citing a source marked that source as "challenged." Target vs evidence is a semantic distinction that must live in a column, per feedback: "links must not disappear into vague JSON."
**Alternatives rejected:**
- Convention that `input_artifact_ids[0]` is the target — fragile, not queryable by type system.
- Separate `challenges` / `revisions` tables — collapses the 3-entity model.
**Revisit:** never in v1.

## 2026-04-24 — Step `created_at` is client-supplied
**Decision:** `StepCreate.created_at` is a required field. Server validates timezone-awareness and `<= now + 60s`. Included in `step_hash`. Artifact `created_at` remains server-generated (not in content_hash).
**Why:** The prior design made signed steps impossible to sign end-to-end — the client couldn't know the server's `created_at`. Rather than add a `/steps/preview` endpoint (extra round-trip, extra surface), we let the client own the timestamp. This matches an append-only ledger: the client records what it did; DW faithfully stores it.
**Alternatives rejected:**
- `/steps/preview` endpoint — adds a round-trip and doubles the surface.
- Server overwrites client-provided `created_at` — breaks signatures.
**Revisit if:** malicious clock manipulation becomes a concern (would add clock-skew rejection tightening).

## 2026-04-24 — Exactly-one body, UTF-8 byte cap
**Decision:** `ArtifactCreate` rejects payloads that set both `body_text` and `body_base64`, or neither. Size cap is measured as UTF-8 encoded bytes for text, base64 character length for binary.
**Why:** Prior "at least one" check was looser than the published contract. Measuring Python string length let multibyte text bypass the 10MB cap.
**Revisit:** never — this is a hardened contract.

## 2026-04-24 — Local only, no GitHub ceremony yet
**Decision:** No GitHub repo, no CI, no deploy in v1.
**Why:** Feedback: "do not waste time on GitHub ceremony before the skeleton exists."
**Revisit:** after first green run of the vertical slice.
