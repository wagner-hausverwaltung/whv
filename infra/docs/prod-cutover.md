# Production cutover runbook

How to stand up **production** on a dedicated Hetzner box, separate from
staging (which stays for testing). Staging stays at `staging.*`; prod takes
the bare domains `api.` / `admin.` / `portal.` / `sign.wagner-hausverwaltung.com`.

Scaffolding this runbook references (all committed):

| File | Purpose |
|------|---------|
| `Caddyfile.prod` | Bare-domain TLS vhosts (rsynced to the host as `Caddyfile`). |
| `docker-compose.prod.yml` | Prod override (`APP_ENV=prod`, https URLs, Caddy, DocuSeal). |
| `.env.prod.example` | Prod env template — copy to `.env` on the host, fill in. |
| `.github/workflows/deploy-prod.yml` | **Manual** (`workflow_dispatch`) prod deploy. |

> ⚠️ Two app-level guards (shipped in the audit hardening): with `APP_ENV=prod`
> the backend **refuses to boot** if `JWT_SECRET` is the default/empty, or if a
> CORS origin is localhost / plain-http. The prod `.env` + compose already set
> these correctly — just don't blank them.

---

## 0. Decide: who owns `sign.*` (DocuSeal)?

`sign.wagner-hausverwaltung.com` is a single host. Today it runs on staging.
For prod, either:
- **Move it to prod** — repoint `sign.*` DNS at the prod box and migrate the
  `docuseal-data` volume (signed PDFs + SQLite DB) off staging, **or**
- **Leave it on staging** and drop the `sign` vhost + `docuseal` service from
  the prod compose/Caddyfile (the admin iframe would still point at the
  staging DocuSeal — acceptable only short-term).

The scaffolding assumes prod owns signing. Volume migration:
`docker run --rm -v docuseal-data:/from -v $PWD:/to alpine tar czf /to/docuseal.tgz -C /from .`
then restore into the prod volume.

## 1. Provision the prod server

- New Hetzner Cloud box (Nürnberg), same class as staging (cax21 / arm64 — the
  images are built `linux/arm64`).
- Install Docker + compose plugin; create the `whv` user; `mkdir -p /home/whv/whv`.
- Open ports 80 + 443 only.

## 2. DNS (A records → prod box IP)

| Host | → |
|------|---|
| `api.wagner-hausverwaltung.com` | prod IP |
| `admin.wagner-hausverwaltung.com` | prod IP |
| `portal.wagner-hausverwaltung.com` | prod IP |
| `sign.wagner-hausverwaltung.com` | prod IP *(if prod owns DocuSeal — §0)* |

Records must resolve **before** the first deploy, or Caddy's Let's Encrypt
HTTP-01 challenge fails. Leave the `staging.*` records pointing at staging.

## 3. 🔴 Rotate every secret (do NOT reuse staging / dev values)

Generate fresh for prod and put in the host `.env` (see `.env.prod.example`):

- `JWT_SECRET` — `python -c 'import secrets; print(secrets.token_urlsafe(48))'`
- `POSTGRES_PASSWORD`
- `DOCUSEAL_SECRET_KEY_BASE` — `openssl rand -hex 64`
- `DOCUSEAL_WEBHOOK_SECRET`
- **AWS SES SMTP creds** (the `AKIA…` user used in dev was exposed — issue a new IAM SMTP credential)
- `IMPOWER_API_TOKEN` + `IMPOWER_WEBHOOK_SECRET` (prod instance — §5)
- `RESEND_API_KEY`, `GEMINI_API_KEY`, AWS inbound IAM key/secret
- Reset the `wagner@` (and any seeded) account password; the dev temp password must not exist in prod.

## 4. GitHub secrets for `deploy-prod.yml`

Add repo secrets:
- `PROD_SSH_HOST` — prod box IP / hostname
- `PROD_SSH_KEY` — private key whose public half is in the prod `whv` user's `authorized_keys`

(Staging keeps using `STAGING_SSH_HOST` / `STAGING_SSH_KEY`.)

## 5. Impower TEST → prod

- `.env`: `IMPOWER_API_BASE=https://api.app.impower.de/v2` + prod token + prod webhook secret.
- Point Impower's outbound webhooks at `https://api.wagner-hausverwaltung.com/webhooks/impower`.
- ⚠️ **Data in Impower must never be deleted.** The sync is read/ingest only;
  double-check no destructive call path is exercised against the prod instance.

## 6. SES production access

The account is in the SES **sandbox** (can only send to verified addresses).
Before real owner email goes out:
- Request production access (SES console → Account dashboard).
- Verify the sending domain + DKIM/SPF for `wagner-hausverwaltung.com`.
- Confirm the inbound receipt rule (S3 + SNS → `/webhooks/email/inbound`) is wired for prod.

## 7. First deploy

1. Copy `.env.prod.example` → `/home/whv/whv/.env` on the prod box; fill in §3 values.
2. From the Actions tab run **deploy-prod** with confirm = `deploy-prod`
   (or `gh workflow run deploy-prod.yml -f confirm=deploy-prod`).
3. The workflow builds the prod-baked web image (`whv-web:prod-<sha>`), pushes,
   rsyncs compose + `Caddyfile.prod`→`Caddyfile`, runs `alembic upgrade head`,
   `up -d`, reloads Caddy, and checks `/healthz`.
4. **First run only:** after the deploy, `docker compose … restart caddy` on the
   host so Caddy issues certs for the new vhosts + applies the `frame-ancestors`
   header (reload is not enough for new vhosts / header changes).

## 8. Verify (read-only smoke checks)

```
curl -s -o /dev/null -w "%{http_code}\n" https://api.wagner-hausverwaltung.com/healthz      # 200
curl -s -o /dev/null -w "%{http_code}\n" https://api.wagner-hausverwaltung.com/docs         # 404 (docs gated in prod)
curl -s -o /dev/null -w "%{http_code}\n" https://api.wagner-hausverwaltung.com/admin/property-images/00000000-0000-0000-0000-000000000000.png  # 401 (auth-gated)
```
Then: log in on `admin.` + `portal.`, confirm CORS works (no console errors),
load a property switcher photo, send a test ticket email, embed DocuSeal.

## 9. iOS prod build

- Point `APIClient` at `https://api.wagner-hausverwaltung.com` for Release
  (Debug stays on staging). Confirm `APNS_USE_SANDBOX=false` on the backend.
- Marketing version is already `1.0.0`; bump the build number, archive, and
  upload via the existing `ios/Scripts/testflight.sh` pipeline.

## 10. Rollback

- App regression: re-run **deploy-prod** pinned to a previous good sha
  (`IMAGE_TAG`/`WEB_IMAGE_TAG` resolve from it), or on the host
  `IMAGE_TAG=<old> WEB_IMAGE_TAG=prod-<old> docker compose … up -d`.
- Migrations are forward-only — a bad migration needs a fix-forward, so test on
  staging first (the bare-domain split means staging is a true rehearsal env).
