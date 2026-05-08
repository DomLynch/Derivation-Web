# Research Agent Bot ↔ Derivation Web — Integration Brief

> **Audience:** the agent that owns the `research-agent-bot` repo. Paste this
> brief (or its path) into a fresh session in that repo. Self-contained — does
> not require reading any other DW doc, but `INTEGRATION.md` is the
> authoritative wire contract if you want full detail.

## Goal

`research-agent-bot` synthesizes draft papers from source documents. Every
synthesis run leaves a permanent, tamper-evident record in DW so the resulting
paper carries cryptographic provenance from day one.

This is the **producer-side wire**. Researka's accept/reject wire (already
live) layers a `classify` step on top of the bot's `infer` step. The result is
a chain: sources → bot synthesis → Researka decision → (later) OSF
registration. DW is the spine; everyone writes onto it.

## What you produce in DW per synthesis run

For each draft paper the bot generates:

1. **N source artifacts** — one per input document the bot ingested. Each
   carries the actual content (text or base64) + metadata (URL/DOI/title).
2. **1 claim artifact** — the draft paper itself (paper.md content).
3. **1 step** — type `infer`, inputs = the N source IDs, output = the claim
   ID, actor = `research-agent-bot:v1`, method = model/prompt/run details.

## Endpoints

Base URL: `https://dw.domlynch.com` (HTTPS only — HTTP redirects)
Auth: `Authorization: Bearer <key>` on every POST. `X-API-Key: <key>`
also accepted. Reads (GET) require no key.

```
POST /api/actors                 — first-time actor registration (idempotent)
POST /api/artifacts              — register source or claim (idempotent on
                                   (content_hash, actor_id) — same actor
                                   POSTing same content gets same ID back)
POST /api/steps                  — link sources → claim
GET  /api/artifacts/{id}         — retrieve a single artifact
GET  /api/artifacts/{id}/chain   — retrieve full provenance chain (verification)
```

Full wire contract: `INTEGRATION.md` in the DW repo. Shape Researka uses is
the shape you use.

## Auth setup (operator, once per machine the bot runs on)

On Brain VPS:
```bash
ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18
set -a; . /etc/derivation-web/env; set +a
PY=/opt/derivation-web/.venv/bin/python
$PY -m derivation_web.tools.issue_key issue --client-id research-agent-bot
```

Save the printed raw key to a file ON THE MACHINE THE BOT RUNS ON at
`/etc/research-agent-bot/dw_api.key`, `root:root` `0600`. Never commit it,
never paste it in chat. The bot reads from that file at startup.

To rotate later:
```bash
$PY -m derivation_web.tools.issue_key revoke --key-id <id>
$PY -m derivation_web.tools.issue_key issue --client-id research-agent-bot
```
…and overwrite the file. Effect of revoke is immediate (next request 401).

## Code shape

Add a new module owning ALL DW interaction (e.g. `bot/derivation_web.py`
or wherever your runtime layer lives). Everyone else calls this module; this
module owns the HTTP.

```python
# Pseudocode — adapt to your HTTP client (httpx/requests) and config layer.

from datetime import UTC, datetime
from pathlib import Path
import logging

import httpx

logger = logging.getLogger(__name__)


class DerivationWeb:
    ACTOR_ID = "research-agent-bot:v1"
    BASE_URL = "https://dw.domlynch.com"

    def __init__(self, key_path: str = "/etc/research-agent-bot/dw_api.key"):
        self._headers = {
            "Authorization": f"Bearer {Path(key_path).read_text().strip()}",
            "Content-Type": "application/json",
        }
        self._client = httpx.Client(
            base_url=self.BASE_URL, headers=self._headers, timeout=10.0
        )
        self._ensure_actor()

    def _ensure_actor(self) -> None:
        # First call ever: register. Later calls: 409 (exists) is fine.
        r = self._client.post("/api/actors", json={
            "id": self.ACTOR_ID,
            "kind": "agent",
            "name": "Research Agent Bot v1",
        })
        if r.status_code not in (201, 409):
            raise RuntimeError(f"DW actor register failed: {r.status_code} {r.text}")

    def register_source(self, body_text: str, metadata: dict) -> str:
        r = self._client.post("/api/artifacts", json={
            "kind": "source",
            "content_type": "text/plain",
            "body_text": body_text,
            "metadata": metadata,
            "actor_id": self.ACTOR_ID,
        })
        r.raise_for_status()
        return r.json()["id"]

    def register_claim(self, body_text: str, metadata: dict) -> str:
        r = self._client.post("/api/artifacts", json={
            "kind": "claim",
            "content_type": "text/markdown",
            "body_text": body_text,
            "metadata": metadata,
            "actor_id": self.ACTOR_ID,
        })
        r.raise_for_status()
        return r.json()["id"]

    def register_synthesis_step(
        self, source_ids: list[str], claim_id: str, method: dict
    ) -> str:
        r = self._client.post("/api/steps", json={
            "step_type": "infer",
            "input_artifact_ids": source_ids,
            "output_artifact_id": claim_id,
            "target_artifact_id": None,
            "actor_id": self.ACTOR_ID,
            "method": method,
            "created_at": datetime.now(UTC).isoformat(),
        })
        r.raise_for_status()
        return r.json()["id"]

    def emit_synthesis(
        self,
        sources: list[dict],   # [{"text": "...", "metadata": {...}}]
        draft_text: str,
        draft_metadata: dict,
        method: dict,
    ) -> dict:
        """Best-effort. Returns {ok, claim_id, source_ids, error}.
        NEVER raises into the bot's main pipeline — DW is provenance,
        not a critical-path dependency.
        """
        try:
            source_ids = [
                self.register_source(s["text"], s["metadata"]) for s in sources
            ]
            claim_id = self.register_claim(draft_text, draft_metadata)
            self.register_synthesis_step(source_ids, claim_id, method)
            return {"ok": True, "claim_id": claim_id, "source_ids": source_ids}
        except Exception as e:
            logger.warning("DW emit failed (non-blocking): %s", e)
            return {"ok": False, "error": str(e)}
```

## Hook point

In the bot pipeline, wherever the synthesis stage finishes producing the
draft — call `emit_synthesis(...)` at the end of that path. Capture the
`claim_id` from the return and stash it on the draft so Researka (or
downstream consumers) can reference it.

```python
# Somewhere in your synthesis pipeline:
result = dw.emit_synthesis(
    sources=[{"text": doc.text, "metadata": {"url": doc.url, "doi": doc.doi}}
             for doc in inputs],
    draft_text=draft.markdown,
    draft_metadata={
        "title": draft.title,
        "bundle_url": draft.bundle_uri,   # the 19-file bundle, not stored in DW
        "agent_run_id": run_id,
    },
    method={
        "model": "claude-opus-4.7",
        "prompt_hash": prompt_sha256,
        "temperature": 0,
        "agent_run_id": run_id,
    },
)
draft.dw_claim_id = result.get("claim_id")
draft.save()
```

## Failure handling (non-blocking discipline)

- **4xx from DW** → log at ERROR + skip the emit. This is a bug in your wire
  payload; alarm the operator.
- **5xx / timeout / connection refused** → log at WARNING + skip. DW is
  having a bad day; your draft still ships. DW will be back; you can backfill
  later.
- **No in-line retries.** If you want resilience, add a separate
  "dw-backfill" cron that scans drafts with `dw_claim_id IS NULL` and retries.
  Don't bake retries into the synthesis pipeline.
- **Per-call timeout: 10s.** Generous for any single request given DW's load.

## Step `method` JSON — what to put in it

Freeform JSON. Recommended:
```json
{
  "model": "claude-opus-4.7",
  "prompt_hash": "sha256:<64-hex>",
  "temperature": 0,
  "bundle_url": "s3://bot-runs/run_xyz/",
  "agent_run_id": "run_xyz",
  "n_sources_total": 5,
  "n_sources_used": 5
}
```
This goes into `step_hash`, so the run is reproducible AND the integrity
of (sources, prompt, output) is provable. Don't put secrets here.

## Smoke test (after deploy)

```bash
# Trigger one real synthesis end-to-end. Capture the claim_id.
# Then verify the chain:
curl https://dw.domlynch.com/api/artifacts/<claim_id>/chain | jq

# Expected shape:
# - root_id == <claim_id>
# - nodes[0] = the claim (depth 0)
# - nodes[1..N] = the source artifacts (depth 1), each with producing_step=null
# - the claim's producing_step.step_type == "infer"
# - producing_step.actor_id == "research-agent-bot:v1"
```

Then trigger a Researka review on that claim and re-fetch the chain. Researka
should write a `classify` step. Chain depth grows.

## Out of scope (do NOT do these in v1)

- **Step signatures (Ed25519).** Optional, can be added later. Skip for v1.
- **Sharding the bundle into multiple artifacts.** One claim = one paper.
  The 19-file bundle is referenced by URL in metadata, not stored in DW.
- **OSF / DOI publishing.** Separate cron job, not the bot's job.
- **Mutating or deleting DW artifacts.** DW is append-only.
- **Inventing your own `synthesize` step type.** Use `infer` (closest match
  in the existing enum). If `synthesize` is genuinely needed, propose it as
  a DW v1.1 schema change — don't fork the contract.

## Acceptance criteria

1. Bot has a `derivation_web.py` (or equivalent) module owning all DW HTTP.
2. After every synthesis, source artifacts + claim + step are registered in
   DW. Verifiable: `curl /api/artifacts/<claim_id>/chain` returns the tree.
3. If DW is down, the bot still produces and saves the draft locally
   (non-blocking confirmed by stopping `derivation-web.service` on Brain and
   running a synthesis — bot completes, logs DW WARN, draft is on disk).
4. The Researka wire (already live) successfully writes a `classify` step
   on top of a bot-produced claim. End-to-end chain has depth ≥ 2.
5. `draft.dw_claim_id` is persisted in the bot's local store so the bot can
   reference its DW counterpart in subsequent steps (revisions, etc.).

## What NOT to copy from Researka's wire

| | Researka | Bot |
|---|---|---|
| `kind` of source | the original submission | each input document used in synthesis |
| `kind` of claim | the decision (accept/reject) | the draft paper |
| `step_type` | `classify` | `infer` |
| `actor_id` | `researka:v2` | `research-agent-bot:v1` |
| API key client_id | `researka` | `research-agent-bot` |

Different identities, different keys, different roles in the chain. The
boundary is what makes provenance meaningful.

## Coordination with Researka (out-of-band)

Researka needs to know "which claim ID did the bot produce" so it can layer
its `classify` step on top. The bot must write `dw_claim_id` to wherever
Researka reads its queue (DB row, file, message bus — your call). That's a
bot↔Researka coordination, NOT a DW concern. DW just records.

## Estimated work

~50 LOC for the wire module, ~10 LOC at the synthesis hook point, a smoke
test. **Half a day** if you have the bot's HTTP conventions handy.
