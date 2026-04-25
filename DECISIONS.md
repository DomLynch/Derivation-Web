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

## 2026-04-25 — Manual gates, no GitHub Actions (SUPERSEDED 2026-04-25)
**Decision:** Run `ruff check . && mypy derivation_web && pytest -q` locally before every push. No `.github/workflows/`.
**Why:** Solo dev, GH Actions billing not desired, single-laptop discipline is sufficient for v1. Workflow file would just sit dormant; deletion is the deletion-pass-friendly answer (rule 7).
**Superseded by** "GitHub Actions + repo public" entry below — independent reviewer flagged that an auth-bearing public service needs a server-side gate that `--no-verify` cannot bypass. Keeping this entry as history so future readers see the reasoning of both passes.

## 2026-04-25 — GitHub Actions + repo public (belt and suspenders)
**Decision:** Restore `.github/workflows/ci.yml`. Flip repo to PUBLIC (free Actions on public repos). Keep `.githooks/pre-push` as a fast local gate.
**Why:**
- Pre-push hook alone can be bypassed with `git push --no-verify` and is absent on a fresh clone until `core.hooksPath` is configured. For an auth-bearing public service that's below AAA.
- Public repo = free Actions, no payment, runs on every push and PR regardless of bypass intent.
- Repo has no secrets (verified via history scan); substrate ethos already implies "Researka is customer zero, not the container," so open is consistent.
- Two layers, two failure modes: hook catches regressions in seconds locally; Actions is the authoritative gate that blocks merges.
**Alternatives rejected:**
- Self-hosted runner on VPS2 — extra attack surface (runner executes any code in repo as the runner user); not earned by current threat model.
- Hook-only — bypassable, not server-enforced.
**Revisit if:** the repo needs to go private (license, IP, etc.); then either self-host a runner or pay for Actions minutes.

## 2026-04-25 — Tailscale-only deploy until auth ships
**Decision:** First VPS deploy bound to `100.96.74.1:8080` (Tailscale interface). No public DNS, no nginx, no SSL.
**Why:** Per playbook rule 43 — high-blast-radius (auth-touching) changes require a blast-fence. Tailscale-only listener IS the fence: literal kernel-level "service is not on a public interface", verified via `ss -tlnp` + connection-refused from public IP. Cannot be bypassed by misconfiguration the way an nginx allowlist can.
**Alternatives rejected:**
- Public deploy with no auth — open POSTs to the internet, anyone can forge artifacts.
- Public deploy with nginx basic-auth — couples auth to the proxy layer, can't revoke per-client without nginx reload.
- Cloudflare Access tunnel — extra dependency, extra failure mode, extra cost surface.
**Revisit:** when API-key auth is verified working (this commit + next).

## 2026-04-25 — API-key transport auth, separate from step signatures
**Decision:** Add API-key auth on `POST /actors`, `POST /artifacts`, `POST /steps`. Header: `Authorization: Bearer <key>` or `X-API-Key: <key>`. Read endpoints unauthenticated. One key per integration (Researka first). Server stores SHA-256 hashes, never raw keys.
**Why:** Auth and signatures answer two different questions:
- API key = *transport*: who is allowed to call DW.
- Ed25519 signature = *production*: who produced and stands behind this step.
Conflating them (e.g. binding a key to an actor_id) would make Researka unable to submit steps on behalf of multiple agents under one server credential. Keep them orthogonal.
**Schema:** `api_keys (id, key_hash UNIQUE, client_id, created_at, revoked_at NULLABLE)`. No `last_used_at` (write per request violates perf budget; not needed for v1).
**Threat model considered:**
- DB leak → only hashes exposed; raw keys uncrackable from sha256 of 256-bit secret.
- Sniff over wire → keys travel only over HTTPS once public DNS lands; never expose service over plain HTTP.
- Timing attack on hash compare → DB indexed lookup on `key_hash`; sha256 itself is constant-time.
- Replay of a captured request → out of scope for v1 (acceptable given append-only and HTTPS); revisit if needed.
- Compromised key → operator runs `python -m derivation_web.tools.issue_key revoke --key-id <id>`; takes effect on next request.
- Lockout from misconfigured dep → rollback via `git revert` + `systemctl restart`; kill switch via `systemctl stop derivation-web`.
**Out of scope (v1):** rate limiting, scopes (read/write split), per-actor binding, OAuth/JWT/OIDC, key rotation (issue new + revoke old is sufficient).
**Alternatives rejected:**
- Bind API key to a single `actor_id` — breaks Researka submitting on behalf of multiple agents.
- Skip API key, rely on Ed25519 signatures alone — signatures only prove producer identity; they don't gate writes (anyone can submit a signed-by-Alice step *as long as Alice already published a pubkey*).
- nginx-level basic auth — can't revoke programmatically, mixes layers.
**Revisit if:** rate limiting becomes urgent, or multi-tenant isolation is needed.

## 2026-04-25 — Public DNS via nginx + Let's Encrypt, bind unchanged
**Decision:** Front DW with nginx at `dw.domlynch.com`. nginx upstream proxies to `http://100.96.74.1:8080`. Let's Encrypt issues a cert via certbot (HTTP-01). HTTP redirects to HTTPS.
**Why:** Standard pattern on Brain (matches mcp.domlynch.com). Keeping uvicorn bound to Tailscale IP rather than `127.0.0.1` lets us verify post-deploy that even if nginx is removed, no public listener remains — extra defense.
**Alternatives rejected:**
- Bind uvicorn to `0.0.0.0` + ufw rules — easier to misconfigure firewall than to misconfigure interface bind.
- Cloudflare-fronted — extra dependency, hides the real client IP unless we configure trusted proxies, blurs blast-radius reasoning.
**Revisit if:** subdomain consolidation or Cloudflare-specific features become valuable.
