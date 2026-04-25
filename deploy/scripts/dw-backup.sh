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

echo "$(date -Iseconds): dw-backup $OUT $(du -h "$OUT" | cut -f1)"

# OFF-BOX COPY (operator wires this up):
#
#   Add to /etc/derivation-web/env (or a separate include):
#     OFFBOX_TARGET=user@offbox-host:/path/to/dw-backups/
#     # OR for S3-compatible:
#     # OFFBOX_S3_BUCKET=s3://bucket/dw-backups/
#
#   Then append to this script (above retention, below the dump):
#     [[ -n "${OFFBOX_TARGET:-}" ]] && rsync -e 'ssh -i /root/.ssh/offbox' "$OUT" "$OFFBOX_TARGET"
#     [[ -n "${OFFBOX_S3_BUCKET:-}" ]] && aws s3 cp "$OUT" "$OFFBOX_S3_BUCKET"
#
# Rotation can stay local-only; the off-box copy is the disaster-recovery layer.
