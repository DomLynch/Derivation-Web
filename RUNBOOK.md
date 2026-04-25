# Operations Runbook — Derivation Web

Designed for "0 to hero in a week or two." Keep this short; if it grows past
~150 lines, split it.

## Contents
- [Service topology](#service-topology)
- [Daily commands](#daily-commands)
- [Incident: site is down / 5xx](#incident-site-is-down)
- [Incident: a key was leaked](#incident-key-leaked)
- [Incident: bad code shipped](#incident-bad-code)
- [Incident: DB corrupted / data loss](#incident-db-corrupted)
- [Routine: deploy a change](#routine-deploy)
- [Routine: rotate the cert manually](#routine-rotate-cert)
- [Off-box backups (operator must wire)](#offbox-backups)

---

<a id="service-topology"></a>
## Service topology

```
public ──HTTPS──▶ nginx (443) ──proxy──▶ uvicorn (100.96.74.1:8080, 4 workers)
                                                  │
                                                  └──▶ Postgres (127.0.0.1:5432, db=dw)
```

- **VPS:** Brain (49.12.7.18 / Tailscale 100.96.74.1)
- **Code:** `/opt/derivation-web`, owner `dw:dw` except `.git/` is `root:root`
- **Service:** `derivation-web.service` (systemd)
- **Env:** `/etc/derivation-web/env` (root:dw 0640) — DATABASE_URL, DW_MAX_ARTIFACT_BYTES
- **API key file:** `/etc/derivation-web/researka.key` (root:root 0600)
- **Backups:** `/var/backups/derivation-web/dw-*.sql.gz` (last 14 days, local) + `root@100.97.248.77:/var/dw-backups/` (Brain Backup VPS2 over Tailscale, accumulating)
- **Cert:** `/etc/letsencrypt/live/dw.domlynch.com/`
- **Timers:** `derivation-web-backup.timer` (02:11 daily), `certbot-dw.timer` (03:17 daily)

---

<a id="daily-commands"></a>
## Daily commands

```bash
ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18

# Health
systemctl status derivation-web nginx postgresql
curl -s https://dw.domlynch.com/health   # {"status":"ok","db":true}

# Audit log (structured JSON per request)
journalctl -u derivation-web -f --no-pager | grep '"evt":"http"'

# Issue / list / revoke API keys
set -a; . /etc/derivation-web/env; set +a
PY=/opt/derivation-web/.venv/bin/python
$PY -m derivation_web.tools.issue_key list
$PY -m derivation_web.tools.issue_key issue --client-id <name>
$PY -m derivation_web.tools.issue_key revoke --key-id <id>
```

---

<a id="incident-site-is-down"></a>
## Incident: site is down / 5xx

1. `curl -sf https://dw.domlynch.com/health` — does it 200?
2. If no DNS / connection refused: `systemctl status nginx`
3. If 502 from nginx: `systemctl status derivation-web` and look at
   `journalctl -u derivation-web -n 100`
4. If `db: false` in /health: `systemctl status postgresql`
5. If a deploy just landed and broke things: see [bad code](#incident-bad-code)

**Kill switch** (stop accepting writes immediately):
```bash
systemctl stop derivation-web   # nginx now returns 502 for everything
```

---

<a id="incident-key-leaked"></a>
## Incident: a key was leaked

```bash
ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18
set -a; . /etc/derivation-web/env; set +a
PY=/opt/derivation-web/.venv/bin/python

# Find the key_id from the leaked raw key (you'd have to recompute the hash)
# Easier: check `list` for "active" keys and revoke the suspect one.
$PY -m derivation_web.tools.issue_key list
$PY -m derivation_web.tools.issue_key revoke --key-id key_xxxxxxxxxxxx

# Issue a replacement, write directly to file (do not paste into chat / notes):
$PY <<'EOF'
import os, uuid
from derivation_web.api.auth import generate_key
from derivation_web.db import repo
from derivation_web.db.session import make_session
raw, kh = generate_key()
key_id = f"key_{uuid.uuid4().hex[:12]}"
with make_session() as s:
    repo.create_api_key(s, key_id=key_id, key_hash=kh, client_id="researka")
    s.commit()
fd = os.open("/etc/derivation-web/researka.key", os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f: f.write(raw + "\n")
print("key_id:", key_id)
EOF
```

Effect of revoke is immediate (next request 401). Tell the affected
client to fetch the new key.

---

<a id="incident-bad-code"></a>
## Incident: bad code shipped

```bash
ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18
cd /opt/derivation-web
git log --oneline -5                       # find last good SHA
git reset --hard <last-good-sha>           # ⚠️ destructive; alternative: git revert
chown -R dw:dw . && chown -R root:root .git
systemctl restart derivation-web
curl -sf https://dw.domlynch.com/health
```

If a migration was the bad part:
```bash
set -a; . /etc/derivation-web/env; set +a
/opt/derivation-web/.venv/bin/alembic downgrade -1
systemctl restart derivation-web
```

---

<a id="incident-db-corrupted"></a>
## Incident: DB corrupted / data loss

```bash
ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18

# Stop the service so writes don't race the restore
systemctl stop derivation-web

# Pick the most recent good backup. Two locations:
#   local (fast)            : /var/backups/derivation-web/
#   off-box (Brain Backup)  : root@100.97.248.77:/var/dw-backups/   (Tailscale)
# If the local dir is empty / corrupt, pull from off-box first:
#   scp -i /root/.ssh/dw_backup_to_vps2 root@100.97.248.77:/var/dw-backups/dw-<TS>.sql.gz /var/backups/derivation-web/
ls -lt /var/backups/derivation-web/ | head

# Restore (drops + recreates the dw db; keep this surgical)
set -a; . /etc/derivation-web/env; set +a
DB_PASS=$(echo "$DATABASE_URL" | sed -E 's|^[^:]+://[^:]+:([^@]+)@.*$|\1|')
sudo -u postgres psql -c "DROP DATABASE dw"
sudo -u postgres psql -c "CREATE DATABASE dw OWNER dw"
gunzip -c /var/backups/derivation-web/dw-<TS>.sql.gz \
  | PGPASSWORD="$DB_PASS" psql -h 127.0.0.1 -U dw -d dw

systemctl start derivation-web
curl -sf https://dw.domlynch.com/health
```

---

<a id="routine-deploy"></a>
## Routine: deploy a change

On laptop:
```bash
git push                  # pre-push hook runs ruff + mypy + pytest
```

On VPS:
```bash
ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18
cd /opt/derivation-web
git pull --ff-only
chown -R dw:dw . && chown -R root:root .git
# If migrations changed:
set -a; . /etc/derivation-web/env; set +a
/opt/derivation-web/.venv/bin/alembic upgrade head
systemctl restart derivation-web
curl -sf https://dw.domlynch.com/health
```

If systemd unit file or nginx config changed:
```bash
cp /opt/derivation-web/deploy/systemd/derivation-web.service /etc/systemd/system/
systemctl daemon-reload && systemctl restart derivation-web
# nginx vhost or rate-limit:
cp /opt/derivation-web/deploy/nginx/dw.domlynch.com.conf /etc/nginx/sites-available/
cp /opt/derivation-web/deploy/nginx/dw-rate-limit.conf /etc/nginx/conf.d/
nginx -t && systemctl reload nginx
```

---

<a id="routine-rotate-cert"></a>
## Routine: rotate the cert manually

The dedicated `certbot-dw.timer` does this automatically. If you need to force:
```bash
ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18
rm -rf /var/lib/letsencrypt/temp_checkpoint
systemctl start certbot-dw.service
journalctl -u certbot-dw.service -n 20
```

---

<a id="offbox-backups"></a>
## Off-box backups (wired to Brain Backup VPS2 over Tailscale)

Local copy lives in `/var/backups/derivation-web/` on Brain (same VPS
as the DB — would die together). The off-box leg of `dw-backup.sh`
rsyncs each new dump over Tailscale to:

```
root@100.97.248.77:/var/dw-backups/   (Brain Backup, Hetzner VPS2)
```

Wired via two env vars on Brain (`/etc/derivation-web/env`):
- `OFFBOX_RSYNC_TARGET=root@100.97.248.77:/var/dw-backups/`
- `OFFBOX_RSYNC_KEY=/root/.ssh/dw_backup_to_vps2`

A failed off-box step exits the dw-backup.service with status 3 —
visible via `systemctl status dw-backup.service` and journald.
Watch for that on the next morning's check.

**Verify weekly** (don't trust an unverified backup):
```bash
ssh -i ~/.ssh/brain_backup_hetzner root@100.97.248.77 \
    'ls -lt /var/dw-backups/ | head -5'
# Pull yesterday's dump back to your laptop and try a real restore
# against a scratch local Postgres.
```

If Brain Backup itself ever needs replacement, the only thing to
re-create is the SSH authorization: copy
`/root/.ssh/dw_backup_to_vps2.pub` from Brain into the new target's
`~/.ssh/authorized_keys`, update `OFFBOX_RSYNC_TARGET` in env, and
run `dw-backup.service` once to verify.
