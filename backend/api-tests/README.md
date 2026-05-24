# WHV Backend — API collection (Bruno)

This is a [Bruno](https://www.usebruno.com/) collection covering every endpoint exposed by the WHV backend. Bruno was chosen over Postman because the format is plain text — every change shows up in `git diff` and we don't depend on a cloud account.

## Install

```bash
brew install --cask bruno   # macOS
# or grab from https://www.usebruno.com/downloads
```

## Open

Bruno → **Open Collection** → pick this folder (`backend/api-tests`).

## Environments

Two environments ship:

- **local** — `http://localhost:8000` (when you run `docker compose up` locally)
- **staging** — `https://staging.api.wagner-hausverwaltung.com`

Pick one in the top-right environment dropdown.

## Demo loop

1. **Get an invite code** by running the bootstrap CLI on the server (no admin UI yet):
   ```bash
   ssh whv@46.225.185.151 \
     'cd whv && docker compose -f docker-compose.yml -f docker-compose.staging.yml \
       exec -T backend python -m app.auth.bootstrap create-invite YOUR_EMAIL --role verwalter'
   ```
2. **Run `POST /auth/invite/redeem`** (under `auth/`) with the code + your email + a password
3. **Copy `access_token` and `refresh_token`** from the response into the active environment's vars
4. Now everything under `me/` and `webhooks/` works — Bruno auto-fills `Authorization: Bearer {{access_token}}`
5. `GET /me/properties` → copy a property UUID → paste into `GET /me/properties/{id}` and `.../{id}/documents`

## Refreshing the access token

`POST /auth/refresh` returns a new pair. Update both `access_token` and `refresh_token` in the environment; the old refresh token is revoked immediately after rotation.

## Layout

```
api-tests/
  bruno.json              collection meta
  environments/
    local.bru             http://localhost:8000
    staging.bru           https://staging.api.wagner-hausverwaltung.com
  meta/                   healthz, readyz (no auth)
  auth/                   invite-redeem, login, refresh, logout
  me/                     get-me, my-properties, property-detail,
                          property-documents, export, delete-me
  webhooks/               impower-event (manual replay/test only;
                          in prod the call is from Impower)
```
