# Researka ↔ Derivation Web — Integration Contract

> **Direction (frozen, v1): Researka is a DW client; DW is the authoritative provenance store.**
> Researka POSTs derivations into DW over HTTPS. DW never calls Researka. If
> Researka later needs push-style updates, add a DW → Researka webhook as a
> secondary path; do not invert the primary contract.

This is the seam. Freezing it early lets Researka wire in without forcing DW
schema changes. Researka is customer zero; this contract is the whole point
of separating the substrate from the consumer.

## Boundary
- **DW never calls an LLM.** It records what Researka produced.
- **DW never calls Researka.** Researka initiates every write.
- Researka can change agents, prompts, models freely. DW only sees artifacts
  and steps it is told about.
- DW appends only. No mutation of artifacts or steps.

---

## Authentication

All `POST` endpoints (`/actors`, `/artifacts`, `/steps`) require an API key.
`GET` endpoints (`/artifacts/{id}`, `/artifacts/{id}/chain`, `/health`) are
unauthenticated.

```http
Authorization: Bearer dwk_<43-char-urlsafe-base64>
# or, equivalently:
X-API-Key: dwk_<43-char-urlsafe-base64>
```

- Keys are scoped per-client (e.g. one for Researka). The DW operator issues
  them on the server and hands the raw key over once. Only the SHA-256 hash
  is persisted; lost keys cannot be recovered, only revoked + replaced.
- API key auth and Ed25519 step signatures answer different questions:
  - **API key**: who is allowed to call DW (transport).
  - **Step signature**: who produced and stands behind a specific step
    (provenance). The same client may submit signed steps on behalf of
    multiple `actor_id`s under one API key.
- Missing / malformed / unknown / revoked keys all yield `401` with a
  `WWW-Authenticate: Bearer` header. No information is leaked about whether
  a presented key was syntactically valid vs. unknown.

---

## Actors

Every agent, reviewer, or human that produces an artifact is an Actor.

```http
POST /api/actors
Content-Type: application/json

{
  "id": "researka:agent:alice-v3",
  "kind": "agent",
  "name": "Alice (Researka reviewer agent, v3)",
  "pubkey_ed25519_b64": "<optional 44-char base64>"
}
→ 201 { "id": "...", "kind": "...", "name": "...", "pubkey_ed25519_b64": "..." }
```

- `kind`: `human | agent | model | system`
- `id` is opaque to DW. Recommended Researka convention:
  `researka:<role>:<handle>[:v<n>]`.
- `pubkey_ed25519_b64` is optional. If set, any step this actor produces may
  carry a signature, and DW will verify it.

---

## Artifacts

Every inspectable object becomes an Artifact: source paper, extract,
summary, claim, reviewer note, revision body.

```http
POST /api/artifacts

{
  "kind": "source",
  "content_type": "application/json",
  "body_text": "...",
  "body_base64": null,
  "metadata": {
    "title": "...",
    "doi": "10.1234/...",
    "url": "https://...",
    "researka_ref": "paper_abc"
  },
  "actor_id": "researka:agent:alice-v3"
}
→ 201 { "id": "art_<hex>", "content_hash": "<sha256 hex>", ... }
```

- `kind`: `source | claim | challenge | revision`
- **Exactly one** of `body_text` / `body_base64` must be set. DW rejects
  payloads that set both or neither.
- Size cap: the body, measured as UTF-8 bytes (text) or base64 characters
  (binary), must be ≤ 10 MB.
- `content_hash = sha256(canonical({kind, content_type, body_text, body_base64, metadata}))`.
  Researka can compute this locally (Python `json.dumps(obj, sort_keys=True,
  separators=(",",":"), ensure_ascii=False).encode("utf-8")` → SHA-256) and
  assert equality.
- **Idempotent per `(content_hash, actor_id)`.** The same actor POSTing the
  same content twice returns the existing artifact. A *different* actor
  POSTing the same content creates a new, distinctly attributed artifact —
  creator provenance is never silently merged.

---

## Steps

Every transform becomes a Step. One step per produced artifact — DW rejects
attempts to register a second producing step for the same `output_artifact_id`.

```http
POST /api/steps

{
  "step_type": "summarize",
  "input_artifact_ids": ["art_src1", "art_src2"],
  "output_artifact_id": "art_claim",
  "target_artifact_id": null,
  "actor_id": "researka:agent:alice-v3",
  "method": {
    "model": "claude-opus-4-7",
    "prompt_hash": "sha256:...",
    "temperature": 0,
    "researka_run_id": "run_abc"
  },
  "created_at": "2026-04-24T12:34:56.789+00:00",
  "signature_b64": null
}
→ 201 { "id": "step_<hex>", "step_hash": "<sha256 hex>", ... }
```

- `step_type`: `summarize | extract | infer | calculate | classify | compare | revise | challenge`
- **`created_at` is client-supplied** (timezone-aware ISO 8601). DW accepts
  any past timestamp and up to 60s of clock skew into the future. Making
  this client-stable is what allows signatures to round-trip: the client
  already knows every field that goes into `step_hash` before submission.
- `step_hash = sha256(canonical({step_type, input_artifact_ids,
  output_artifact_id, target_artifact_id, actor_id, method,
  created_at_iso}))`.
- **Input order is semantic.** `compare([A, B])` ≠ `compare([B, A])` to DW.
  Sort at the client only if your step type is commutative.
- If `signature_b64` is set, the actor must have a `pubkey_ed25519_b64` on
  file. Signature must verify against `step_hash` (UTF-8 string).

### Inputs vs target: challenges and revisions

For `challenge` and `revise` steps:
- `target_artifact_id` — **required**. The artifact being challenged /
  revised. This is the explicit semantic edge.
- `input_artifact_ids` — **evidence only**. May be empty. Artifacts that
  justify the challenge / revision (e.g. contradicting sources).

For all other step types (`summarize`, `extract`, `infer`, `calculate`,
`classify`, `compare`):
- `target_artifact_id` — **must be null**.
- `input_artifact_ids` — **required, non-empty**. The sources consumed to
  produce `output_artifact_id`.

This separation fixes the obvious trap: a challenge citing evidence must
not accidentally mark that evidence as "challenged." Only the explicit
`target_artifact_id` is challenged.

---

## Challenges & revisions — full flow

```http
# Challenge "art_claim" with two pieces of contradicting evidence:
POST /api/artifacts { "kind": "challenge", "body_text": "reason...", "actor_id": "..." }
→ { "id": "art_ch1", ... }
POST /api/steps {
  "step_type": "challenge",
  "input_artifact_ids": ["art_ev1", "art_ev2"],
  "output_artifact_id": "art_ch1",
  "target_artifact_id": "art_claim",
  "actor_id": "...",
  "method": { "reason_code": "overstated" },
  "created_at": "2026-04-24T12:00:00+00:00"
}

# Revise "art_claim" based on the challenge:
POST /api/artifacts { "kind": "revision", "body_text": "revised text", "actor_id": "..." }
→ { "id": "art_rev1", ... }
POST /api/steps {
  "step_type": "revise",
  "input_artifact_ids": ["art_ch1"],
  "output_artifact_id": "art_rev1",
  "target_artifact_id": "art_claim",
  "actor_id": "...",
  "method": { "based_on_challenge": "art_ch1" },
  "created_at": "2026-04-24T12:05:00+00:00"
}
```

---

## Retrieval

```http
GET /api/artifacts/{id}           # single artifact
GET /api/artifacts/{id}/chain     # full backward provenance, annotated
```

Chain response shape:

```json
{
  "root_id": "art_claim",
  "nodes": [
    {
      "artifact": { ... },
      "producing_step": { ... } | null,
      "depth": 0,
      "challenges": [{ "artifact": {...}, "step": {...} }, ...],
      "revisions":  [{ "artifact": {...}, "step": {...} }, ...]
    }
    // depth 1..N follow
  ]
}
```

- Root (`depth: 0`) is always the requested artifact.
- Nodes are emitted in BFS order from root → leaf sources.
- Each node carries its producing step plus annotations whose
  `target_artifact_id` equals that node — evidence inputs are NOT
  confused with targets.

---

## Signing round-trip

Because `created_at` is client-supplied, a complete signing flow is:

```python
from datetime import datetime, timezone
from hashlib import sha256
import json
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

created_at = datetime.now(timezone.utc)
payload = {
    "step_type": "summarize",
    "input_artifact_ids": [src_id],
    "output_artifact_id": out_id,
    "target_artifact_id": None,
    "actor_id": actor_id,
    "method": {},
    "created_at": created_at.isoformat(),
}
digest = sha256(
    json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
).hexdigest()
signature = base64.b64encode(priv.sign(digest.encode("utf-8"))).decode()

client.post("/api/steps", json={**payload, "signature_b64": signature})
```

---

## Stable v1 guarantees

1. `content_hash` and `step_hash` formulas will not change in v1.
2. Actor `id` is opaque and caller-defined.
3. Artifacts dedupe on `(content_hash, actor_id)`. Cross-actor submissions
   never silently merge.
4. At most one producing step per artifact, enforced by DB.
5. `target_artifact_id` is the single semantic edge for challenges and
   revisions. Inputs are evidence only.
6. Step `created_at` is client-supplied; DW validates clock skew but does
   not overwrite it.
7. DW appends only — no mutation or delete endpoints in v1.

## Non-guarantees (subject to change)

- Query/search beyond the endpoints above.
- Trust scores, reputation, aggregate views.
- Bulk/batch POSTs.
- Webhook callbacks.
- Streaming retrieval.
