#!/usr/bin/env bash
# Daily Postgres backup for the WHV staging stack.
#
# Runs pg_dump inside the running postgres container (so it works against
# whatever password/user docker-compose has wired up), streams gzip out,
# writes to /var/backups/postgres/whv-YYYY-MM-DD.sql.gz, and prunes files
# older than $RETENTION_DAYS.
#
# Installed as /usr/local/bin/backup-postgres.sh and run by the
# whv-backup.timer systemd unit at 03:00 UTC daily.
#
# Restore drill: see infra/docs/backups.md.

set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/var/backups/postgres}
RETENTION_DAYS=${RETENTION_DAYS:-30}
REPO_ROOT=${REPO_ROOT:-/home/whv/whv}
COMPOSE="docker compose -f $REPO_ROOT/docker-compose.yml -f $REPO_ROOT/docker-compose.staging.yml"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TIMESTAMP=$(date -u +%F)
OUTPUT="$BACKUP_DIR/whv-$TIMESTAMP.sql.gz"

# Atomic write: dump → .tmp, then mv. Avoids leaving partial backups.
cd "$REPO_ROOT"
$COMPOSE exec -T postgres \
    pg_dump -U whv -d whv --no-owner --no-privileges \
    | gzip -9 > "$OUTPUT.tmp"
mv "$OUTPUT.tmp" "$OUTPUT"
chmod 600 "$OUTPUT"

# Prune older backups.
find "$BACKUP_DIR" -name 'whv-*.sql.gz' -type f -mtime +"$RETENTION_DAYS" -delete

SIZE=$(du -h "$OUTPUT" | cut -f1)
echo "[$(date -u -Iseconds)] backup OK → $OUTPUT ($SIZE)"
echo "recent backups:"
ls -1t "$BACKUP_DIR" | head -5 | sed 's/^/  /'
