# ADR-0010 — APNs push notifications (token-based), email-parity events

**Status:** accepted
**Date:** 2026-05-28
**Deciders:** Luis Wagner

## Context

The portal + iOS app already email the right people when three
things happen:

- a new **ETV comment** is posted (→ Verwalter + thread participants)
- a **ticket message** arrives (→ Verwalter / creator / participants)
- a **new ticket** is created (→ Verwalter)

Owners + Verwalter asked to get the same nudges as a phone push, not
only email — "Handy gleichziehen mit Email".

## Decision

### Auth: token-based (.p8), not certificate

One APNs Auth Key (.p8) signed as an ES256 JWT. Works for sandbox +
production + every app under the team, never expires, no yearly cert
rotation. PyJWT[crypto] (already a dep) does the signing; the JWT is
cached + refreshed every 45 min (Apple rejects tokens > 1h old and
rate-limits regenerating faster than every 20 min).

### Transport

httpx with the `http2` extra (added `h2`) → `api.push.apple.com`
(prod) / `api.development.push.apple.com` (sandbox). One POST per
device token to `/3/device/{token}`.

### Device registry

`user_devices` table — one row per (user, APNs token):
- `POST /me/devices` upserts on the token (re-register bumps
  `last_seen_at`, re-points to the current user, un-deletes).
- `DELETE /me/devices/{token}` soft-deletes on sign-out.
- `environment` (SANDBOX/PRODUCTION) stamped at register time — a
  token is only valid against the host that minted it, so a Debug
  build's sandbox token and a TestFlight build's production token
  never get sent to the wrong gateway.

### Fan-out

`app/services/push.notify_users(session, user_ids, title, body,
deep_link, thread_id)`:
- Loads each user's non-deleted devices matching the configured
  environment.
- Sends via APNSClient; soft-deletes any token APNs reports 410
  Unregistered / BadDeviceToken.
- Wired into the **exact same three notification sites** as email,
  reusing the same recipient resolution (`list[User]` for ETV,
  email→User lookup for tickets). Email stays the system of record;
  push is best-effort and never breaks the write path.

Deep links: each push carries `whv://etv/<id>` / `whv://tickets/<id>`
in a custom `whv.deep_link` payload key. iOS routes the tap through
the existing `DeepLinkRouter` — same path widgets + universal links
use.

### Disabled-when-unconfigured

Empty `apns_key_p8` → `APNSClient.is_configured` is False and the
service no-ops, exactly like an empty Resend key disables email. So
staging without the key just doesn't push; nothing else breaks.

## Consequences

- **Apple-side prerequisites** (one-time, Luis):
  1. Enable **Push Notifications** capability on App ID
     `com.wagner-hausverwaltung.portal` in the Developer Portal.
  2. Create an **APNs Auth Key** (Keys → +, tick Apple Push
     Notifications service) → download the `.p8`, note the **Key
     ID**.
  3. Note the **Team ID** (Membership page).
  4. Set on the backend: `APNS_KEY_P8` (the .p8 contents),
     `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_USE_SANDBOX`
     (true on staging for Xcode/dev builds, false for the
     TestFlight/prod path).
- **Per-build environment**: the iOS `aps-environment` entitlement
  is `development` in Debug, flipped to `production` at archive
  time. The app registers the matching environment string so the
  backend routes correctly. A TestFlight build's token will not
  receive pushes from a sandbox-configured backend and vice versa —
  this is the single most common "why no push" gotcha.
- **No per-category mute yet** — push fires for exactly the email
  events, to the same recipients. A Settings toggle is a planned
  fast-follow; iOS system-level disable already works.
- **Single-process fan-out** — sends run inline in the request like
  the email sends. If push volume grows, move both onto Celery; the
  `notify_users` interface stays put.

## Alternatives considered

- **Certificate (.p12) auth** — per-app, yearly expiry, separate
  sandbox/prod certs. Rejected; token-based is strictly simpler.
- **Third-party push (Firebase, OneSignal)** — adds an SDK + a
  privacy-manifest entry + another data processor in the DSGVO
  chain. Not worth it for direct APNs to our own devices.
- **Celery-queued sends now** — premature; volume is tiny
  (handful of recipients per event). Inline keeps the failure
  surface small.
