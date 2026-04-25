#!/usr/bin/env bash
# Daily Postgres backup for derivation-web.
# Run by dw-backup.timer (systemd). Reads DATABASE_URL from env file.
#
# Layout:
#   /var/backups/derivation-web/dw-YYYYMMDD-HHMMSSZ.sql.gz   (local, 14-day rotation)
#   $OFFBOX_RSYNC_TARGET                                    (off-box, accumulating)
# Off-box rsync is REQUIRED for production: missing config or rsync
# failure both exit non-zero. To intentionally disable (single-host
# dev only), set OFFBOX_RSYNC_DISABLED=1 in /etc/derivation-web/env.

set -euo pipefail

BACKUP_DIR=/var/backups/derivation-web
RETENTION_DAYS=14

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "dw-backup: DATABASE_URL not set (load /etc/derivation-web/env first)" >&2
    exit 1
fi

# Parse DATABASE_URL via Python (urllib.parse handles URI-encoded chars
# in user/password — sed regexes break on @ or : in credentials).
# Output is one field per line: user, password, host, port, database.
PARSED=$(python3 -c "
from urllib.parse import urlparse
import os
url = os.environ['DATABASE_URL'].replace('postgresql+psycopg://', 'postgresql://')
u = urlparse(url)
print(u.username or '')
print(u.password or '')
print(u.hostname or '')
print(u.port or 5432)
print((u.path or '').lstrip('/'))
")
readarray -t pg_parts <<< "$PARSED"
export PGUSER="${pg_parts[0]}"
export PGPASSWORD="${pg_parts[1]}"
export PGHOST="${pg_parts[2]}"
export PGPORT="${pg_parts[3]}"
export PGDATABASE="${pg_parts[4]}"

TS=$(date -u +%Y%m%d-%H%M%SZ)
OUT="$BACKUP_DIR/dw-$TS.sql.gz"

# pg_dump picks up PG* env vars automatically; no creds on the command line.
pg_dump \
    --no-owner --no-privileges --serializable-deferrable \
  | gzip -9 > "$OUT"

chmod 600 "$OUT"

# Retention: drop dumps older than RETENTION_DAYS
find "$BACKUP_DIR" -maxdepth 1 -name 'dw-*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete

# Sanity: refuse to silently produce empty dumps
SIZE=$(stat -c %s "$OUT")
if [[ "$SIZE" -lt 1024 ]]; then
    echo "dw-backup: $OUT is suspiciously small ($SIZE bytes) — failing loud" >&2
    exit 2
fi

echo "$(date -Iseconds): dw-backup local $OUT $(du -h "$OUT" | cut -f1)"

# Off-box copy. Required for launch — local backups die with the VPS.
#   OFFBOX_RSYNC_TARGET=root@<host>:/path/   (e.g. root@100.97.248.77:/var/dw-backups/)
#   OFFBOX_RSYNC_KEY=/root/.ssh/<key>        (private key authorized on target)
#
# Missing config and rsync failure are BOTH treated as failures: silent
# off-box loss for weeks is exactly how disaster recovery breaks when
# you finally need it. To intentionally disable, set
#   OFFBOX_RSYNC_DISABLED=1   (logs + exits 0).
if [[ "${OFFBOX_RSYNC_DISABLED:-}" == "1" ]]; then
    echo "$(date -Iseconds): dw-backup offbox DISABLED (OFFBOX_RSYNC_DISABLED=1)" >&2
elif [[ -z "${OFFBOX_RSYNC_TARGET:-}" || -z "${OFFBOX_RSYNC_KEY:-}" || ! -f "${OFFBOX_RSYNC_KEY:-/dev/null}" ]]; then
    echo "$(date -Iseconds): dw-backup offbox MISSING CONFIG — set OFFBOX_RSYNC_TARGET + OFFBOX_RSYNC_KEY in /etc/derivation-web/env, or set OFFBOX_RSYNC_DISABLED=1 to suppress this check" >&2
    exit 4
elif rsync -a -e "ssh -i ${OFFBOX_RSYNC_KEY} -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15" \
        "$OUT" "$OFFBOX_RSYNC_TARGET"; then
    echo "$(date -Iseconds): dw-backup offbox $OUT -> $OFFBOX_RSYNC_TARGET"
else
    echo "$(date -Iseconds): dw-backup offbox FAILED to $OFFBOX_RSYNC_TARGET" >&2
    exit 3
fi
