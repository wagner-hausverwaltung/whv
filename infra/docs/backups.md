# Database backups

## Current setup (2026-05-24)

- **Frequency**: daily at 03:00 UTC
- **Mechanism**: systemd timer `whv-backup.timer` invokes `/usr/local/bin/backup-postgres.sh`, which runs `pg_dump` inside the running `postgres` container
- **Format**: gzipped SQL (`pg_dump --no-owner --no-privileges` + `gzip -9`)
- **Local copy**: `/var/backups/postgres/whv-YYYY-MM-DD.sql.gz` on the server (staging since 2026-05-24, prod see below), 30-day retention, auto-pruned by the script
- **Off-site copy** (DR): Backblaze B2 bucket `whv-staging-postgres-backups`, uploaded by `rclone` after each successful local write, same 30-day retention. Bucket is private, SSE-B2 encryption at rest, account key scoped read+write to this bucket only (no `listAllBucketNames`).

## Install (already done on staging)

```bash
sudo install -m 755 /home/whv/whv/infra/scripts/backup-postgres.sh /usr/local/bin/
sudo install -m 644 /home/whv/whv/infra/systemd/whv-backup.service /etc/systemd/system/
sudo install -m 644 /home/whv/whv/infra/systemd/whv-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now whv-backup.timer
```

## Prod (whv-prod-api, 91.99.123.40)

Until 2026-08-21 prod had **no** backup at all (only `dpkg-db-backup.timer`); it was
noticed before a kernel reboot and a one-off `pg_dumpall` was taken to
`/var/backups/whv-pre-upgrade/` by hand. The setup is the staging one, with a systemd
drop-in that points the script at the prod compose file and a prod bucket. The script
only `exec`s into the running `postgres` service; it never creates or recreates anything.

### 1. Local daily dumps (do this first — works without B2)

```bash
# On prod, as root
install -m 755 /home/whv/whv/infra/scripts/backup-postgres.sh /usr/local/bin/
install -m 644 /home/whv/whv/infra/systemd/whv-backup.service /etc/systemd/system/
install -m 644 /home/whv/whv/infra/systemd/whv-backup.timer /etc/systemd/system/
install -d -m 755 /etc/systemd/system/whv-backup.service.d
install -m 644 /home/whv/whv/infra/systemd/whv-backup-prod.conf /etc/systemd/system/whv-backup.service.d/prod.conf
systemctl daemon-reload
systemctl enable --now whv-backup.timer
systemctl start whv-backup.service          # first dump now, not at 03:00
journalctl -u whv-backup -n 12 --no-pager   # expect "local backup OK" and a
                                            # "skipping off-site upload" line until step 2
ls -l /var/backups/postgres/
```

`/home/whv/whv` on prod must contain the merged `infra/` (it is a git checkout: `git pull`
as `whv` first if the files are missing).

### 2. Off-site copy to B2

Create the bucket and a key in the B2 console exactly like the staging ones (see the
section below): bucket **`whv-prod-postgres-backups`** (private, SSE-B2), application key
scoped **read+write to that bucket only**, no `listAllBucketNames`. Then on prod, as
root, `apt-get install -y rclone` and write `/etc/rclone.conf` (mode 600) with the
`[b2]` block as below — the remote name `b2` and the bucket name are what the drop-in's
`RCLONE_REMOTE=b2:whv-prod-postgres-backups` expects. Verify with
`systemctl start whv-backup.service && journalctl -u whv-backup -n 6 --no-pager` — the
log must now say "off-site upload OK". Never reuse the staging key: it is scoped to the
staging bucket and the upload would fail (the script logs a WARN and keeps the local copy).

### 3. Notice when it stops

`host-health` (slr-pipeline repo) runs nightly on both boxes and mails on failed systemd
units, so a failing `whv-backup.service` reaches the inbox the next morning. A dump that is
silently *stale* is not caught that way — `ls -l /var/backups/postgres/` belongs in the
monthly check until a freshness check is wired in.

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
