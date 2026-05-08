# OSF Publisher ↔ Derivation Web — Integration Brief

> **Audience:** the agent that builds the OSF publisher service. This service
> watches DW for high-confidence claims, registers them at the Open Science
> Framework (or any registry), and writes the resulting DOI back into DW as
> another step in the same provenance chain. **Self-contained brief.**

## Goal

When a claim reaches the "publish-worthy" bar (e.g. Researka stamps it with
`method.confidence = "AAA"` on a `classify` step), an external service should:

1. Push the claim to OSF (or arXiv / PubMed / Zenodo — the registry is
   pluggable).
2. Capture the DOI (or registry URL) returned.
3. Write a `register` step back into DW with the DOI in metadata.

Result: every paper in DW grows another node in its chain when it gets a
permanent registry ID. Searching DW by DOI becomes free. Future agents
verifying provenance can replay the full chain → claim → DOI in one query.

## Why a separate service (not inside DW)

DW's invariant: append-only ledger, never calls outbound, no external
dependencies. Putting OSF logic inside DW gives it side effects, retry
loops, OSF API auth, and DOI persistence — a bigger surface area and
new failure modes that didn't exist before.

The publisher is a **separate process**, runs as a systemd timer next to
`dw-backup.timer` on Brain (or wherever — it's portable). It reads from
DW + OSF, writes to OSF + DW. DW stays narrow.

## Where to run

Recommended: same VPS as DW (Brain) for now. Two reasons:
- Direct Postgres access for the cursor query (no DW endpoint change required).
- Localhost write-back to DW (no nginx hop).

Alternative: any VPS that can reach `provenance.researka.org` and OSF. Migration is
trivial — change a connection string + a URL.

## Prerequisite: small DW v1.1 schema additions (the DW agent does this)

Before the publisher can write back cleanly, DW needs to accept two new
enum values. **Coordinate with the DW agent BEFORE building the publisher.**

```python
# derivation_web/core/models.py
class ArtifactKind(StrEnum):
    SOURCE = "source"
    CLAIM = "claim"
    CHALLENGE = "challenge"
    REVISION = "revision"
    REGISTRY_RECORD = "registry_record"   # NEW

class StepType(StrEnum):
    ...existing...
    REGISTER = "register"                   # NEW
```

Plus: add `REGISTER` to `ANNOTATION_STEP_TYPES` so the chain walker treats
it as an annotation on the targeted claim (same shape as `challenge` and
`revise`). No new tables, no migration — just enum widening.

If DW hasn't shipped the enum widening yet, the publisher should refuse to
start (early-fail) rather than silently fall back to a workaround.

## Cursor query (read side)

The publisher runs every N minutes (start at 15 min). Each run:

```sql
-- Find claims that have been "AAA-classified" but not yet registered.
SELECT DISTINCT classify_step.output_artifact_id AS claim_id,
                classify_step.method->>'confidence' AS confidence
FROM steps classify_step
WHERE classify_step.step_type = 'classify'
  AND classify_step.method->>'confidence' = 'AAA'
  AND NOT EXISTS (
      SELECT 1 FROM steps register_step
      WHERE register_step.step_type = 'register'
        AND register_step.target_artifact_id = classify_step.output_artifact_id
  )
ORDER BY classify_step.created_at
LIMIT 100;
```

**State lives in DW itself.** No state file. A claim is "to be registered"
iff there's a `classify` step with AAA AND no corresponding `register`
step. Restart-safe, idempotent, crash-safe.

## OSF write side (per claim)

For each `claim_id` from the query:

1. `GET https://provenance.researka.org/api/artifacts/{claim_id}` — fetch the body
2. Build the OSF payload (title from artifact metadata, body_text as content,
   any bundle URL referenced in metadata gets attached)
3. `POST https://api.osf.io/v2/nodes/` (or whatever endpoint OSF currently
   uses for new registrations — verify in their docs)
4. Capture the returned `doi` and `osf_url`

If step 3 fails (4xx, 5xx, timeout): skip this claim, log, move on. Will
retry next run because the cursor query still picks it up.

## DW write-back (per claim, after OSF success)

Two POSTs to DW:

```http
POST https://provenance.researka.org/api/artifacts
Authorization: Bearer <publisher's DW key>
{
  "kind": "registry_record",
  "content_type": "application/json",
  "body_text": "{\"registry\":\"osf\",\"doi\":\"10.17605/...\",\"url\":\"https://osf.io/abc\"}",
  "metadata": {
    "registry": "osf",
    "doi": "10.17605/...",
    "registered_at": "2026-04-26T..."
  },
  "actor_id": "osf-publisher:v1"
}
→ {"id": "art_<reg_record_id>", ...}

POST https://provenance.researka.org/api/steps
{
  "step_type": "register",
  "input_artifact_ids": [],
  "output_artifact_id": "art_<reg_record_id>",
  "target_artifact_id": "<claim_id>",
  "actor_id": "osf-publisher:v1",
  "method": {
    "registry": "osf",
    "doi": "10.17605/...",
    "osf_node_id": "abc123"
  },
  "created_at": "<iso8601 UTC>"
}
```

The `register` step has `target_artifact_id` = the claim being registered
(this is what makes future "show me all registrations of claim X" queries
trivial).

## Auth (operator does once)

DW key for the publisher (separate from Researka and bot keys):

```bash
ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18
set -a; . /etc/derivation-web/env; set +a
PY=/opt/derivation-web/.venv/bin/python
$PY -m derivation_web.tools.issue_key issue --client-id osf-publisher
# save to /etc/osf-publisher/dw_api.key  (root:root 0600)
```

OSF API token (one-time, from your OSF account settings):
```bash
# /etc/osf-publisher/osf_token.key  (root:root 0600)
```

Both files referenced from `/etc/osf-publisher/env`:
```
DW_BASE_URL=https://provenance.researka.org
DW_API_KEY_PATH=/etc/osf-publisher/dw_api.key
DW_DB_URL=postgresql+psycopg://osf_reader:<pw>@127.0.0.1:5432/dw   # read-only role
OSF_BASE_URL=https://api.osf.io/v2
OSF_TOKEN_PATH=/etc/osf-publisher/osf_token.key
RUN_INTERVAL_MINUTES=15
```

Create a Postgres read-only role for the cursor query so the publisher
cannot write to DW's tables directly (it must use the public API):
```sql
CREATE ROLE osf_reader LOGIN PASSWORD '<random>';
GRANT CONNECT ON DATABASE dw TO osf_reader;
GRANT USAGE ON SCHEMA public TO osf_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO osf_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO osf_reader;
```

## Code shape

```python
# /opt/osf-publisher/osf_publisher.py  (~200 LOC)
import json, logging, os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)
ACTOR_ID = "osf-publisher:v1"


def find_claims_to_register(conn) -> list[str]:
    rows = conn.execute(text("""
        SELECT DISTINCT classify_step.output_artifact_id AS claim_id
        FROM steps classify_step
        WHERE classify_step.step_type = 'classify'
          AND classify_step.method->>'confidence' = 'AAA'
          AND NOT EXISTS (
              SELECT 1 FROM steps register_step
              WHERE register_step.step_type = 'register'
                AND register_step.target_artifact_id = classify_step.output_artifact_id
          )
        ORDER BY classify_step.created_at LIMIT 100
    """))
    return [r.claim_id for r in rows]


def fetch_claim(dw: httpx.Client, claim_id: str) -> dict:
    r = dw.get(f"/api/artifacts/{claim_id}")
    r.raise_for_status()
    return r.json()


def push_to_osf(osf: httpx.Client, claim: dict) -> dict:
    payload = {
        "data": {
            "type": "nodes",
            "attributes": {
                "title": claim["metadata"].get("title", claim["id"]),
                "category": "data",
                "description": (claim.get("body_text") or "")[:500],
            }
        }
    }
    r = osf.post("/nodes/", json=payload)
    r.raise_for_status()
    body = r.json()
    return {
        "doi": body["data"]["attributes"].get("doi"),
        "osf_node_id": body["data"]["id"],
        "osf_url": body["data"]["links"].get("html"),
    }


def write_register_step(dw: httpx.Client, claim_id: str, osf_info: dict) -> None:
    art = dw.post("/api/artifacts", json={
        "kind": "registry_record",
        "content_type": "application/json",
        "body_text": json.dumps(osf_info, separators=(",", ":")),
        "metadata": {"registry": "osf", **osf_info,
                     "registered_at": datetime.now(UTC).isoformat()},
        "actor_id": ACTOR_ID,
    })
    art.raise_for_status()
    record_id = art.json()["id"]
    step = dw.post("/api/steps", json={
        "step_type": "register",
        "input_artifact_ids": [],
        "output_artifact_id": record_id,
        "target_artifact_id": claim_id,
        "actor_id": ACTOR_ID,
        "method": {"registry": "osf", **osf_info},
        "created_at": datetime.now(UTC).isoformat(),
    })
    step.raise_for_status()


def run_once() -> dict:
    env = lambda k: os.environ[k]
    dw_key = Path(env("DW_API_KEY_PATH")).read_text().strip()
    osf_token = Path(env("OSF_TOKEN_PATH")).read_text().strip()
    dw = httpx.Client(base_url=env("DW_BASE_URL"),
                     headers={"Authorization": f"Bearer {dw_key}"}, timeout=15)
    osf = httpx.Client(base_url=env("OSF_BASE_URL"),
                      headers={"Authorization": f"Bearer {osf_token}"}, timeout=30)
    engine = create_engine(env("DW_DB_URL"))
    registered, skipped, failed = 0, 0, 0
    with engine.begin() as conn:
        claim_ids = find_claims_to_register(conn)
    for claim_id in claim_ids:
        try:
            claim = fetch_claim(dw, claim_id)
            osf_info = push_to_osf(osf, claim)
            write_register_step(dw, claim_id, osf_info)
            registered += 1
            logger.info("registered %s -> %s", claim_id, osf_info.get("doi"))
        except httpx.HTTPStatusError as e:
            failed += 1
            logger.warning("OSF/DW error on %s: %s", claim_id, e)
        except Exception as e:
            failed += 1
            logger.exception("unexpected on %s: %s", claim_id, e)
    return {"registered": registered, "skipped": skipped, "failed": failed,
            "candidates": len(claim_ids)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                       format="%(asctime)s %(levelname)s %(message)s")
    result = run_once()
    logger.info("run done: %s", result)
```

## Systemd units

`/etc/systemd/system/osf-publisher.service`:
```ini
[Unit]
Description=OSF Publisher (DW → OSF DOI registration)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=/etc/osf-publisher/env
ExecStart=/opt/osf-publisher/.venv/bin/python /opt/osf-publisher/osf_publisher.py
```

`/etc/systemd/system/osf-publisher.timer`:
```ini
[Unit]
Description=Run OSF publisher every 15 minutes

[Timer]
OnCalendar=*-*-* *:00/15:00
RandomizedDelaySec=2min
Persistent=true

[Install]
WantedBy=timers.target
```

## Failure handling

- OSF down → log + skip claim. Next run picks it up (cursor is idempotent).
- DW down → log + skip claim. Next run picks it up.
- Partial registration (OSF succeeded, DW write-back failed) → claim is now
  registered at OSF but DW doesn't know. Next run will re-register (DOUBLE
  REGISTRATION at OSF). To prevent: write-back to DW first with a placeholder,
  then OSF, then update — or accept double registration as rare and recoverable.
  **Recommendation v1: accept the rare double registration**; it's idempotent
  if your OSF call uses a deterministic title. Log loud when it happens.
- DW Postgres role permissions error → fail-loud (probably a deploy issue).
- `register` step type not yet in DW enum → fail-loud at startup with
  clear "DW v1.1 enum widening required" message.

## Smoke test

1. Operator manually marks one existing claim as AAA via psql:
   `UPDATE steps SET method = jsonb_set(method, '{confidence}', '"AAA"') WHERE id = 'step_xxx';`
2. Run the publisher manually: `systemctl start osf-publisher.service`
3. Verify: `journalctl -u osf-publisher -n 30`
4. Verify chain extended:
   ```bash
   curl https://provenance.researka.org/api/artifacts/<claim_id>/chain | jq '.nodes[] | select(.producing_step.step_type=="register" or .artifact.kind=="registry_record")'
   ```
   Should show the new registry_record artifact and the `register` step.

## Out of scope (v1)

- **Multi-registry support.** Start OSF-only. Add arXiv/PubMed by adding
  another publisher service with the same shape — DW doesn't change.
- **Retracting registrations.** OSF supports it; we don't (yet). If a claim
  is challenged after registration, the chain reflects that — registry
  status doesn't auto-revert.
- **Bundle attachments.** v1 publishes title + description only. Bundle
  attachment (the 19-file Researka bundle) is a v1.1 enhancement.
- **Webhooks from DW.** Polling is fine at this scale (15 min cadence). If
  load grows, DW could emit a queue event, but not yet earned.

## Acceptance criteria

1. DW enum widening (`registry_record`, `register`) shipped + tested.
2. `osf_reader` Postgres role created + tested.
3. Publisher runs every 15 min via timer, reads cursor query, writes back
   register steps for AAA claims.
4. End-to-end smoke: a manually-AAA-flagged claim gets registered at OSF,
   chain shows the `register` annotation.
5. If OSF or DW is down, publisher logs and exits — no partial state in DW.
6. Restart-safe: kill mid-run, restart — picks up where it left off without
   double-registering already-completed claims.

## Estimated work

~200 LOC publisher + ~30 LOC of systemd + ~20 LOC of DW enum widening
+ smoke test. **One day** including OSF API exploration + auth setup.
