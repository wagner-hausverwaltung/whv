# CI/CD — staging deploys

`.github/workflows/deploy.yml` builds the backend image, pushes to GHCR, and SSHes to staging to pull + apply migrations + restart the services.

## Triggers

- **Auto** on push to `main` when any of these change: `backend/**`, the compose files, `Caddyfile`, or the workflow itself.
- **Manual** via Actions → `deploy-staging` → **Run workflow**.

## Pipeline

```
push → build (linux/arm64) → push to GHCR → ssh whv@staging → docker compose pull →
       alembic upgrade head → docker compose up -d backend worker beat →
       curl /healthz until 200
```

Tags pushed: `:latest` and `:abc1234` (short commit SHA — atomic, traceable).

## Concurrency

`concurrency: deploy-staging` with `cancel-in-progress: false` — a fresh push waits its turn rather than aborting a half-applied deploy.

## Secrets used

Set under https://github.com/wagner-hausverwaltung/whv/settings/secrets/actions:

| Secret | Value |
|---|---|
| `STAGING_SSH_KEY` | Private ed25519 key whose public half lives in `/home/whv/.ssh/authorized_keys` on the server. Generated 2026-05-24, comment `whv-ci-deploy`. |
| `STAGING_SSH_HOST` | `46.225.185.151` |

`GITHUB_TOKEN` (auto) is used for pushing to GHCR; the workflow's `packages: write` permission scope is what authorises it.

## GHCR package visibility

The first successful build creates `ghcr.io/wagner-hausverwaltung/whv-backend`, defaulting to **private**. For the deploy step to `docker pull` without auth on the server, the package needs to be **public**.

One-time flip:

1. After the first successful `build-and-push` job, go to https://github.com/orgs/wagner-hausverwaltung/packages/container/whv-backend/settings  *(or the user equivalent if owned by your personal account)*
2. Scroll to **Danger Zone** → **Change visibility** → **Public** → confirm with the package name

The image bytes only contain our Python source + third-party deps; no secrets (env vars come from `.env` on the server at compose-up time). Risks of public exposure are bounded.

If you'd rather keep it private, the deploy step needs an extra step on the server: `docker login ghcr.io -u USERNAME -p <fine-grained-PAT-with-read:packages>`. That PAT becomes another secret to manage.

## Rolling back

```bash
# Find the desired sha from Actions runs or `gh api ...`
ssh whv@46.225.185.151
cd ~/whv
IMAGE_TAG=abc1234 docker compose -f docker-compose.yml -f docker-compose.staging.yml -f docker-compose.deploy.yml pull backend worker beat
IMAGE_TAG=abc1234 docker compose -f docker-compose.yml -f docker-compose.staging.yml -f docker-compose.deploy.yml up -d --no-deps backend worker beat
```

The previous image stays in GHCR (and in the server's local cache for a while), so rollback is fast.

## What stayed manual

- **rsync of compose files + Caddyfile** still happens from CI to the server — they're not in the image, so they need to land via SCP/rsync. The workflow does this in the `Rsync ...` step.
- **DNS** is not in the pipeline. If you change the staging hostname, update the Caddyfile + the DNS record manually.
- **Secrets** stay on the server's `.env` (perms 600). CI never reads or writes them.
