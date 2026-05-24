# Database backups

## Current setup (2026-05-24)

- **Frequency**: daily at 03:00 UTC
- **Mechanism**: systemd timer `whv-backup.timer` invokes `/usr/local/bin/backup-postgres.sh`, which runs `pg_dump` inside the running `postgres` container
- **Format**: gzipped SQL (`pg_dump --no-owner --no-privileges` + `gzip -9`)
- **Location**: `/var/backups/postgres/whv-YYYY-MM-DD.sql.gz` on the staging server
- **Retention**: 30 days local, auto-pruned by the script
- **Off-site**: **NONE YET** — see "TODO: Backblaze B2" below

## Install (already done on staging)

```bash
sudo install -m 755 /home/whv/whv/infra/scripts/backup-postgres.sh /usr/local/bin/
sudo install -m 644 /home/whv/whv/infra/systemd/whv-backup.service /etc/systemd/system/
sudo install -m 644 /home/whv/whv/infra/systemd/whv-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now whv-backup.timer
```

## Check status

```bash
# Is the timer active?
systemctl status whv-backup.timer

# When is it next scheduled?
systemctl list-timers whv-backup.timer

# What did the last run say?
journalctl -u whv-backup.service --since "yesterday"

# What backups exist?
sudo ls -lht /var/backups/postgres/
```

## Manual run

```bash
sudo systemctl start whv-backup.service
journalctl -u whv-backup.service -f
```

## Restore drill (quarterly per REQUIREMENTS.md §12.3)

```bash
# Pick a backup
BACKUP=/var/backups/postgres/whv-2026-05-24.sql.gz

# Drop the existing DB and restore. THIS WIPES CURRENT DATA — do it
# against a sacrificial DB unless this is a real recovery.
cd /home/whv/whv
docker compose -f docker-compose.yml -f docker-compose.staging.yml exec -T postgres \
    psql -U whv -c "DROP DATABASE IF EXISTS whv_restore_test; CREATE DATABASE whv_restore_test OWNER whv;"

gunzip -c "$BACKUP" | docker compose -f docker-compose.yml -f docker-compose.staging.yml exec -T postgres \
    psql -U whv -d whv_restore_test

# Sanity-check
docker compose -f docker-compose.yml -f docker-compose.staging.yml exec -T postgres \
    psql -U whv -d whv_restore_test -c "SELECT COUNT(*) FROM properties;"

# Cleanup
docker compose -f docker-compose.yml -f docker-compose.staging.yml exec -T postgres \
    psql -U whv -c "DROP DATABASE whv_restore_test;"
```

## TODO: Backblaze B2 off-site

Currently backups live only on the same disk as the database — useless if the disk dies. To finish DR per REQUIREMENTS.md §12.3:

1. Create a Backblaze B2 account + bucket `whv-staging-postgres-backups`
2. Generate an application key with write+list+delete on that bucket only
3. Install `rclone` on the server, configure a `b2:` remote with the key
4. Extend `backup-postgres.sh` to `rclone copy "$OUTPUT" b2:whv-staging-postgres-backups/`
5. Set bucket lifecycle: keep daily for 30 days, weekly for 90 days, monthly for 1 year

Estimated effort: 30 min once the B2 account exists. Track as a follow-up to this hardening pass.
