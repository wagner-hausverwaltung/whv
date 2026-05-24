# Health-check routine

Implements REQUIREMENTS.md §6.7 v1: a scheduled Claude Code routine probing the public health endpoints of WHV staging every 30 min.

## Current scope (v1)

| Probe | Endpoint | Pass criteria |
|---|---|---|
| Liveness | `GET /healthz` | HTTP 200, body `{"status":"ok"}` |
| Readiness | `GET /readyz` | HTTP 200, `deps.postgres == true` AND `deps.redis == true` |

That's it. Auto-remediation (restart containers, renew certs) and Impower probing are deferred to v2 — both need either SSH credentials in the routine's environment or an authenticated `/admin/health` endpoint on staging.

## Setup

The prompt lives at [`infra/scripts/health-checks/routine.md`](../scripts/health-checks/routine.md). To register it as a recurring routine, invoke the `/schedule` skill in Claude Code:

```
/schedule
```

When prompted, give it:
- **name**: `whv-staging-healthcheck`
- **cron**: `*/30 * * * *` (every 30 minutes)
- **prompt**: copy from `infra/scripts/health-checks/routine.md`

The routine runs as a Claude remote agent. Output shows up in your Claude Code routine dashboard.

> **2026-05-24 status:** prompt + docs landed in the repo; **routine registration is pending** — the `/schedule` service returned "trouble connecting with your remote claude.ai account" during initial setup. Retry `/schedule` whenever the service is back; the prompt above is ready to paste.

## Changing the prompt

1. Edit `infra/scripts/health-checks/routine.md`
2. `/schedule` → update the `whv-staging-healthcheck` routine with the new prompt content

The routine doesn't auto-reload from the repo — `/schedule` update is explicit.

## Pausing the routine

Use `/schedule` → pause/disable when:
- Doing planned maintenance (avoid spurious incident notes)
- Migrating the staging host

Don't forget to re-enable.

## Next iterations (v2+)

- **Impower API probe** — needs an authenticated `/admin/health` endpoint on staging that hits `GET /v2/properties?size=1` from the server (using the server's own bearer token) and aggregates the result. Then the routine can probe `/admin/health` with a long-lived admin token. Less coupling than baking the Impower token into the routine secrets.
- **Auto-remediate `unhealthy` containers** — needs deploy SSH key in the routine env. Then the routine can `ssh whv@... 'docker compose ... restart backend'` when `/readyz` is degraded and dep checks suggest a transient container fault.
- **Escalation channel** — Push notification or email when something fails. Today, failures only land in the routine output, which the user has to check manually.
- **More probes** as integrations come online: ePost, WhatsApp BSP, SharePoint Graph, Resend (per REQUIREMENTS.md §6.7).
