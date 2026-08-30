#!/usr/bin/env bash
# Daily Postgres backup for the WHV staging stack.
#
# 1. pg_dump inside the running postgres container → gzip → atomic write
#    to /var/backups/postgres/whv-YYYY-MM-DD.sql.gz
# 2. Prune local backups older than $RETENTION_DAYS
# 3. If rclone is installed AND a usable B2 remote is configured: upload
#    the new file off-site and prune the remote to the same window.
#    Failures here log a WARN but don't fail the script — local backup
#    is the primary, off-site is defense in depth.
#
# Installed as /usr/local/bin/backup-postgres.sh and run by the
# whv-backup.timer systemd unit at 03:00 UTC daily.
#
# Restore drill: see infra/docs/backups.md.

set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/var/backups/postgres}
RETENTION_DAYS=${RETENTION_DAYS:-30}
REPO_ROOT=${REPO_ROOT:-/home/whv/whv}
RCLONE_CONFIG_PATH=${RCLONE_CONFIG_PATH:-/etc/rclone.conf}
RCLONE_REMOTE=${RCLONE_REMOTE:-b2:whv-staging-postgres-backups}
# Prod sets COMPOSE_OVERLAY=docker-compose.prod.yml (+ its own
# RCLONE_REMOTE) via a systemd drop-in; the script itself is host-agnostic.
COMPOSE_OVERLAY=${COMPOSE_OVERLAY:-docker-compose.staging.yml}
COMPOSE="docker compose -f $REPO_ROOT/docker-compose.yml -f $REPO_ROOT/$COMPOSE_OVERLAY"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TIMESTAMP=$(date -u +%F)
OUTPUT="$BACKUP_DIR/whv-$TIMESTAMP.sql.gz"

# --- 1 & 2: local backup + prune ---
cd "$REPO_ROOT"

# The timer can fire right after boot (Persistent+RandomizedDelaySec
# re-triggers on boot) while the container is still starting — wait for
# postgres instead of failing, which turned every auto-reboot into a
# red unit + FAIL mail.
for i in $(seq 1 60); do
    if $COMPOSE exec -T postgres pg_isready -U whv -d whv >/dev/null 2>&1; then
        break
    fi
    if [ "$i" = 60 ]; then
        echo "postgres not ready after 5 minutes; giving up" >&2
        exit 1
    fi
    sleep 5
done

$COMPOSE exec -T postgres \
    pg_dump -U whv -d whv --no-owner --no-privileges \
    | gzip -9 > "$OUTPUT.tmp"
mv "$OUTPUT.tmp" "$OUTPUT"
chmod 600 "$OUTPUT"

find "$BACKUP_DIR" -name 'whv-*.sql.gz' -type f -mtime +"$RETENTION_DAYS" -delete

SIZE=$(du -h "$OUTPUT" | cut -f1)
echo "[$(date -u -Iseconds)] local backup OK → $OUTPUT ($SIZE)"
echo "recent local backups:"
ls -1t "$BACKUP_DIR" | head -5 | sed 's/^/  /'

# --- 3: off-site upload (best-effort) ---
if [ -f "$RCLONE_CONFIG_PATH" ] && command -v rclone >/dev/null 2>&1; then
    echo "[$(date -u -Iseconds)] uploading to $RCLONE_REMOTE"
    if rclone --config="$RCLONE_CONFIG_PATH" copy "$OUTPUT" "$RCLONE_REMOTE/"; then
        echo "[$(date -u -Iseconds)] off-site upload OK"
        # Prune remote older than retention window. --include narrows to our
        # files so we never delete anything unexpected in the bucket.
        rclone --config="$RCLONE_CONFIG_PATH" delete "$RCLONE_REMOTE/" \
            --min-age "${RETENTION_DAYS}d" \
            --include 'whv-*.sql.gz' || true
    else
        echo "[$(date -u -Iseconds)] WARN: off-site upload failed; local backup retained" >&2
    fi
else
    echo "[$(date -u -Iseconds)] rclone or $RCLONE_CONFIG_PATH not available; skipping off-site upload"
fi
