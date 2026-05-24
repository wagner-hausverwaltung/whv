# WHV staging health-check routine

> **What this is:** the prompt fired by the scheduled Claude routine every 30 min.
> Registered via the `/schedule` skill — see `infra/docs/health-checks.md` for setup.
> **Edit this file** to change the routine's behavior; the next scheduled run picks it up only after the routine is `update`d via `/schedule` with the new prompt.

---

## Probe WHV staging and report status.

Run both of these probes:

```
curl -s -o /tmp/whv-healthz -w '%{http_code}' --max-time 10 https://staging.api.wagner-hausverwaltung.com/healthz
curl -s -o /tmp/whv-readyz  -w '%{http_code}' --max-time 10 https://staging.api.wagner-hausverwaltung.com/readyz
```

### Pass criteria (all must be true)

- `/healthz` returns HTTP 200 with body exactly `{"status":"ok"}`
- `/readyz` returns HTTP 200 with body where `deps.postgres == true` AND `deps.redis == true` AND `status == "ok"`

### If everything passes

Output exactly one line:

```
OK <UTC ISO 8601 timestamp>
```

Stop. Do not write files, do not push commits, do not open any other endpoints.

### If anything fails

1. Print a short summary block with the failed probe, HTTP status, latency, and the body excerpt (first 200 chars).
2. Write an incident note to `/tmp/whv-incident-<UTC-date>.md` containing:
   - UTC timestamp of the failure
   - Which probe failed (one or more)
   - Full response body for each failing probe
   - First diagnostic step the on-call should take (e.g., `ssh whv@46.225.185.151 'cd whv && docker compose -f docker-compose.yml -f docker-compose.staging.yml ps'`)
3. Print the note's path at the end of the output so the user can grab it.

### Hard rules

- **DO NOT** SSH into the server.
- **DO NOT** modify any data (no `git push`, no API writes).
- **DO NOT** probe any endpoint other than `/healthz` and `/readyz`.
- The `/admin/health` endpoint for authenticated Impower probing isn't built yet — don't try it.
- Be concise. Successful runs should be one line of output.
