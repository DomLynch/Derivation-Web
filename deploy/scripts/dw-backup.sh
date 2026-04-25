#!/usr/bin/env bash
# Daily Postgres backup for derivation-web.
# Run by dw-backup.timer (systemd). Reads DATABASE_URL from env file.
#
# Layout:
#   /var/backups/derivation-web/dw-YYYYMMDD-HHMMSS.sql.gz
# Retention: 14 days local. Off-box copy is the operator's job — see
# README at the bottom for the recommended one-liner.

set -euo pipefail

BACKUP_DIR=/var/backups/derivation-web
RETENTION_DAYS=14

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

if [[ -z "${DATABASE_URL:-}" ]]; then
    echo "dw-backup: DATABASE_URL not set (load /etc/derivation-web/env first)" >&2
    exit 1
fi

# Parse postgresql+psycopg://user:pass@host:port/dbname
DB_USER=$(echo "$DATABASE_URL" | sed -E 's|^[^:]+://([^:]+):.*$|\1|')
DB_PASS=$(echo "$DATABASE_URL" | sed -E 's|^[^:]+://[^:]+:([^@]+)@.*$|\1|')
DB_HOST=$(echo "$DATABASE_URL" | sed -E 's|^.*@([^:]+):.*$|\1|')
DB_PORT=$(echo "$DATABASE_URL" | sed -E 's|^.*:([0-9]+)/.*$|\1|')
DB_NAME=$(echo "$DATABASE_URL" | sed -E 's|^.*/([^?]+).*$|\1|')

TS=$(date -u +%Y%m%d-%H%M%SZ)
OUT="$BACKUP_DIR/dw-$TS.sql.gz"

PGPASSWORD="$DB_PASS" pg_dump \
    -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" \
    --no-owner --no-privileges --serializable-deferrable \
    "$DB_NAME" \
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

# Off-box copy. Requires both env vars set (see /etc/derivation-web/env):
#   OFFBOX_RSYNC_TARGET=root@<host>:/path/   (e.g. root@100.97.248.77:/var/dw-backups/)
#   OFFBOX_RSYNC_KEY=/root/.ssh/<key>        (private key authorized on target)
# A failure here exits non-zero so systemd surfaces it via journald —
# silent off-box failures over weeks are exactly how disaster recovery
# breaks when you finally need it.
if [[ -n "${OFFBOX_RSYNC_TARGET:-}" && -f "${OFFBOX_RSYNC_KEY:-}" ]]; then
    if rsync -a -e "ssh -i ${OFFBOX_RSYNC_KEY} -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15" \
            "$OUT" "$OFFBOX_RSYNC_TARGET"; then
        echo "$(date -Iseconds): dw-backup offbox $OUT -> $OFFBOX_RSYNC_TARGET"
    else
        echo "$(date -Iseconds): dw-backup offbox FAILED to $OFFBOX_RSYNC_TARGET" >&2
        exit 3
    fi
else
    echo "$(date -Iseconds): dw-backup offbox SKIPPED (OFFBOX_RSYNC_TARGET / OFFBOX_RSYNC_KEY not set)" >&2
fi
