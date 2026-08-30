# Database backups

## Current setup (2026-05-24, prod ergänzt 2026-08-30)

- **Frequency**: daily at 03:00 UTC, **beide Hosts** (staging + prod)
- **Mechanism**: systemd timer `whv-backup.timer` invokes `/usr/local/bin/backup-postgres.sh`, which runs `pg_dump` inside the running `postgres` container. The script waits up to 5 min for `pg_isready` first — the timer can re-fire right after a boot (`Persistent` + `RandomizedDelaySec`) while the container is still starting.
- **Host selection**: the script defaults to the staging compose overlay; prod overrides via drop-in `/etc/systemd/system/whv-backup.service.d/prod.conf` (`COMPOSE_OVERLAY=docker-compose.prod.yml`, own `RCLONE_REMOTE`). The drop-in ships in the repo — `infra/systemd/whv-backup-prod.conf` — so it survives a box rebuild: `install -D -m 644 infra/systemd/whv-backup-prod.conf /etc/systemd/system/whv-backup.service.d/prod.conf && systemctl daemon-reload`.
- **Format**: gzipped SQL (`pg_dump --no-owner --no-privileges` + `gzip -9`)
- **Local copy**: `/var/backups/postgres/whv-YYYY-MM-DD.sql.gz`, 30-day retention, auto-pruned by the script
- **Off-site copy** (DR): Backblaze B2, uploaded by `rclone` after each successful local write, same 30-day retention.
  - staging: bucket `whv-staging-postgres-backups` — läuft. Bucket is private, SSE-B2 encryption at rest, account key scoped read+write to this bucket only (no `listAllBucketNames`).
  - **prod: NOCH OFFEN** — auf prod ist kein rclone/`/etc/rclone.conf` eingerichtet; das Skript loggt das und macht nur das lokale Backup. TODO: B2-Bucket `whv-prod-postgres-backups` + scoped key anlegen, `rclone` installieren, `/etc/rclone.conf` befüllen — dann läuft der Upload ohne weitere Änderung mit.
- **Nicht abgedeckt**: die RAG-`vectordb` (eigener Postgres-Container). Bewusst — der Index ist aus den Dokumenten reproduzierbar (Backfill-Rezept in den RAG-Notizen).
- **Historie**: Bis 2026-08-30 lief das Backup **nur auf staging** — prod (die echten Daten!) hatte keins. Aufgefallen beim Auto-Reboot-Echttest, seitdem läuft es auf beiden Hosts.

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

## B2 off-site setup (already done, here for posterity)

```bash
# On the server, as root:
sudo apt-get install -y rclone

# Write /etc/rclone.conf (perms 600, root-owned)
sudo tee /etc/rclone.conf > /dev/null <<'RC'
[b2]
type = b2
account = <keyID from B2 application key>
key = <applicationKey from B2 application key>
hard_delete = true
RC
sudo chmod 600 /etc/rclone.conf
```

The B2 application key was generated at https://secure.backblaze.com → B2 Cloud Storage → Application Keys → Add New, scoped:

- Allow access to: `whv-staging-postgres-backups` (this bucket only)
- Type: Read and Write
- `Allow List All Bucket Names` unchecked
- No file prefix, no expiry

To rotate: generate a new key in the B2 console, replace the `account`/`key` lines in `/etc/rclone.conf`, run `sudo systemctl start whv-backup.service` to verify, then delete the old key in the console.

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

## Restoring from B2 (if local disk is gone)

```bash
# Pull the latest backup from B2 to wherever you're restoring from
rclone --config=/etc/rclone.conf copy b2:whv-staging-postgres-backups/whv-YYYY-MM-DD.sql.gz .

# Then follow the restore drill above, pointing $BACKUP at the downloaded file.
```

## Possible follow-ups (not yet wired)

- **Tiered retention**: keep daily for 30 days, weekly for 90 days, monthly for 1 year. B2 bucket lifecycle rules can do this — saves storage cost but our daily backups are KBs-MBs, so not urgent.
- **Backup verification**: monthly automated restore drill into a sacrificial database, with a tripwire alert if the restore fails. Right now the only verification is manual.
- **Encryption-in-transit pre-upload**: rclone already uses TLS to B2 and the bucket has SSE-B2 at-rest encryption. Adding client-side encryption (GPG before upload, or rclone's `--crypt` overlay) means B2 can't read the dumps — defense in depth, but more keys to manage.
