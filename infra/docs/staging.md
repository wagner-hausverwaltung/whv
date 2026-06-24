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

## Operational layer

- **Postgres backup**: daily at 03:00 UTC, runbook at [`backups.md`](backups.md). Local-only for now; off-site to B2 is TODO.
- **Health checks**: scheduled Claude routine (every 30 min, when the service is registered) probes `/healthz` + `/readyz`. Prompt at [`health-checks.md`](health-checks.md).
- **Impower webhooks**: connection registered (connection `id: 25815`, state `READY`) — Impower POSTs to `https://staging.api.wagner-hausverwaltung.com/webhooks/impower` on CREATE/UPDATE/DELETE of properties/buildings/units/contracts/contacts/messages/invoices/documents. We currently handle properties/units/contracts/contacts; the rest are acked-and-ignored. CREATE/UPDATE trigger a full entity-type re-sync (v1 simplification); DELETE soft-deletes the local row.

## TLS / DNS

Caddy auto-provisions a Let's Encrypt cert via the HTTP-01 challenge as soon as `staging.api.wagner-hausverwaltung.com` resolves to the server's public IP. While DNS is missing, expect `tls.obtain` errors in Caddy logs every ~60s with exponential backoff — they self-heal once DNS propagates.

Verify externally:

```bash
curl -i https://staging.api.wagner-hausverwaltung.com/healthz
```

## Admin UI host (`staging.admin.wagner-hausverwaltung.com`)

The admin SPA shares the **same React bundle as the portal** — Caddy on this host reverse-proxies to the `web` nginx container (not the backend) and rewrites the root `/` to `/admin` so the bookmark lands on the admin dashboard. Authentication uses the same JWT flow as the portal; Verwalter sign in at the portal's `/login` (or via this host's rewritten `/admin` which falls through to the SPA's login redirect).

Two CORS origins are now allowed on the API: `PORTAL_BASE_URL` (staging.portal.*) **and** `ADMIN_BASE_URL` (staging.admin.*). The Jinja admin UI was removed on 2026-05-25 (commit history); the `whv_admin_session` cookie + `NeedsLoginRedirect` are gone with it.

> Bare-domain hosts (`admin.*`, `portal.*`) are reserved for prod; staging uses the `staging.*` prefix on every public host.

DNS prerequisite — add at the registrar (Bluehost) before the first hit:

| Host                                            | Type | Value             |
|-------------------------------------------------|------|-------------------|
| `staging.admin.wagner-hausverwaltung.com`       | A    | `46.225.185.151`  |

Once the record propagates, Caddy obtains a Let's Encrypt cert on first request (the host is opened on 80/443 already, no firewall change needed).

Smoke after DNS + first deploy:

```bash
# 1. SPA bundle loads (HTML shell with the Vite assets)
curl -i https://staging.admin.wagner-hausverwaltung.com/

# 2. /admin/* paths resolve to the same SPA (nginx try_files → index.html)
curl -i https://staging.admin.wagner-hausverwaltung.com/admin/dashboard
```

Staging compose / deploy env needs:

```
PORTAL_BASE_URL=https://staging.portal.wagner-hausverwaltung.com
ADMIN_BASE_URL=https://staging.admin.wagner-hausverwaltung.com
```

without `ADMIN_BASE_URL`, the admin host's SPA can still load but every API call from it will fail CORS.

## Web portal host (`staging.portal.wagner-hausverwaltung.com`)

The Eigentümer / Mieter / Beirat web portal (React 18 + Vite + Material UI, served by an nginx static container behind Caddy). The SPA calls `staging.api.*` cross-origin via JWT in `Authorization` header; backend's `CORSMiddleware` allowlists this host via `PORTAL_BASE_URL`.

DNS prerequisite — add at the registrar (Bluehost) before the first hit:

| Host                                             | Type | Value             |
|--------------------------------------------------|------|-------------------|
| `staging.portal.wagner-hausverwaltung.com`       | A    | `46.225.185.151`  |

Same provisioning behaviour as the admin host: once DNS resolves, Caddy obtains a Let's Encrypt cert on the first inbound request. If you hit the back-off issue from below (e.g. you set DNS after Caddy already tried + failed), `docker compose restart caddy` clears it.

Smoke after DNS:

```bash
# Static landing renders (HTTP 200, contains "WHV-Portal")
curl -i https://staging.portal.wagner-hausverwaltung.com/

# Auth flow: /login is the default unauth landing, /invite?code= the redemption flow
```

The portal builds at CI time with `VITE_API_BASE_URL=https://staging.api.wagner-hausverwaltung.com` baked into the bundle. If you ever need to redeploy with a different API origin, change the build-arg in `.github/workflows/deploy.yml` and re-push.

### Gotcha: Caddy ACME back-off after late DNS

If you added the host block to the Caddyfile *before* DNS propagated, Caddy's first ACME attempt will have failed and exponential back-off kicks in (10-60 min between retries). `caddy reload` does **not** reset that back-off state. The fix is a container restart:

```bash
ssh whv@46.225.185.151 \
  'cd ~/whv && docker compose -f docker-compose.yml -f docker-compose.staging.yml restart caddy \
     && sleep 2 \
     && docker compose -f docker-compose.yml -f docker-compose.staging.yml logs --tail=30 caddy'
```

Watch for `tls-alpn-01 ... served key authentication certificate` lines from multiple Let's Encrypt validation IPs — that means the challenge succeeded. The cert is valid within ~10 s after that. Subsequent renewals (60-day cadence at 2/3 lifetime) require no manual action. Only the **first** acquisition for a brand-new host is sensitive to this back-off.

### Gotcha: a changed Caddyfile needs a container *recreate*, not `caddy reload`

The Caddyfile is a **single-file bind mount** (`./Caddyfile:/etc/caddy/Caddyfile:ro`). CI rsyncs the new file with an atomic temp-write + rename → the file gets a **new inode**. The running caddy container is still bound to the **old** inode, so `caddy reload` (and `docker compose up -d`, which won't recreate a container just because a bind-mounted file's *contents* changed) silently keep serving the **stale** config — a Caddyfile edit can sit un-applied for weeks this way.

The deploy workflows now recreate caddy after the rsync. If you ever edit the Caddyfile **by hand** on the box, do the same (not `caddy reload`):

```bash
ssh whv@46.225.185.151 \
  'cd ~/whv && docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d --no-deps --force-recreate caddy'
```

(`restart caddy` also re-resolves the mount; `--force-recreate` is the surest, and on prod use the `-f docker-compose.prod.yml` overlay.)
