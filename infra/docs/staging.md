# Staging environment

Provisioned 2026-05-24 on Hetzner Cloud.

## Coordinates

| | |
|---|---|
| Public hostname (target) | `staging.api.wagner-hausverwaltung.com` |
| IPv4 | `46.225.185.151` |
| IPv6 | `2a01:4f8:1c19:bcc2::1` |
| Server | `whv-staging-api`, cax21 (4 vCPU ARM / 8 GB / 80 GB), Ubuntu 24.04 |
| Location | Hetzner Nürnberg (nbg1) |
| SSH | `ssh whv@46.225.185.151` |
| App root | `/home/whv/whv/` |
| Impower env | test instance (`api.prod-replica.develop.impower.de/v2`) |

## Cloud firewall

`whv-staging-public` — Hetzner network-level firewall attached to the server:

| Port | Protocol | Source | Purpose |
|---|---|---|---|
| 22 | tcp | 0.0.0.0/0, ::/0 | SSH |
| 80 | tcp | 0.0.0.0/0, ::/0 | HTTP — ACME challenge + redirect to HTTPS |
| 443 | tcp | 0.0.0.0/0, ::/0 | HTTPS |
| — | icmp | 0.0.0.0/0, ::/0 | ping |

Defense in depth: `ufw` on the server enforces the same defaults.

## Stack

```
internet ─→ Hetzner FW ─→ ufw ─→ Caddy:443 ─→ backend:8000 ─→ postgres / redis
                                  Caddy:80  (ACME + redirect)
```

`docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d`

Postgres, Redis, and the backend have **no host port mappings** in staging — they're reachable only over the default Docker network. Caddy is the only thing on 80/443.

## Secrets

Live in `/home/whv/whv/.env` (perms 600, owned by whv). Generated on the server with `openssl rand -hex` — never on a laptop, never committed.

- `POSTGRES_PASSWORD` — 48 hex chars (24-byte entropy)
- `JWT_SECRET` — 96 hex chars (48-byte entropy)
- `IMPOWER_API_TOKEN` — same test-instance bearer used in dev

To rotate: regenerate, write a new `.env`, then `docker compose ... up -d --force-recreate backend caddy`.

## Common ops

```bash
# Tail backend logs
ssh whv@46.225.185.151 'cd whv && docker compose -f docker-compose.yml -f docker-compose.staging.yml logs -f backend'

# Apply a new migration
ssh whv@46.225.185.151 'cd whv && docker compose -f docker-compose.yml -f docker-compose.staging.yml exec -T backend alembic upgrade head'

# Re-sync Impower master data
ssh whv@46.225.185.151 'cd whv && docker compose -f docker-compose.yml -f docker-compose.staging.yml exec -T backend python -m app.integrations.impower sync all'

# Bootstrap an invite
ssh whv@46.225.185.151 'cd whv && docker compose -f docker-compose.yml -f docker-compose.staging.yml exec -T backend python -m app.auth.bootstrap create-invite EMAIL --role verwalter'
```

## Pushing updates

For now: manual rsync from a dev machine, then rebuild.

```bash
# From repo root on the dev machine
rsync -avz --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.*_cache' \
  --exclude '*.pyc' --exclude '.DS_Store' --exclude '.env' \
  ./ whv@46.225.185.151:/home/whv/whv/

ssh whv@46.225.185.151 'cd whv && docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d --build'
```

GitHub Actions auto-deploy is a follow-up.

## TLS / DNS

Caddy auto-provisions a Let's Encrypt cert via the HTTP-01 challenge as soon as `staging.api.wagner-hausverwaltung.com` resolves to the server's public IP. While DNS is missing, expect `tls.obtain` errors in Caddy logs every ~60s with exponential backoff — they self-heal once DNS propagates.

Verify externally:

```bash
curl -i https://staging.api.wagner-hausverwaltung.com/healthz
```
