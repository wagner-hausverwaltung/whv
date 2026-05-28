# ADR-0011 — Per-user notification preferences (per category × channel)

**Status:** accepted
**Date:** 2026-05-28
**Deciders:** Luis Wagner

## Context

ADR-0010 shipped APNs push as strict email-parity with "no per-category
mute yet … a Settings toggle is a planned fast-follow." This is that
fast-follow. Owners + Verwalter want to choose, per event type, whether
they're nudged by **push**, **email**, both, or neither — and the choice
must follow them across the iOS app and the web portal (one account, one
set of preferences).

## Decision

### Storage — one table, opt-out default

`user_notification_preferences(user_id, category, push_enabled,
email_enabled)`, unique on `(user_id, category)`.

Categories (`notification_category` enum) map 1:1 to the notification
sites:

| category         | fires on                                            |
|------------------|-----------------------------------------------------|
| `ANNOUNCEMENT`   | a Mitteilung/News is published                      |
| `TICKET`         | new Anliegen + new replies                          |
| `ETV_COMMENT`    | new comment on an Eigentümerversammlung             |
| `ETV_INVITATION` | a new Einladung zur ETV arrives (ADR-0010 follow-on)|
| `DOCUMENT`       | a new relevant document is available (**new event**)|

**Opt-out semantics:** the *absence* of a row means "all on." A row is
written only when the user toggles something. So at rollout every
existing user keeps every notification, and a brand-new user does too —
nobody silently loses anything. `filter_user_ids(user_ids, category,
channel)` therefore drops *only* the users who hold a row with that
channel explicitly `False`.

### API — shared by both clients

`GET /me/notification-settings` returns the full 5-row matrix with the
opt-out default applied for missing rows, so the client always renders
the complete grid. `PUT` upserts the whole matrix. The iOS app and the
portal call the identical endpoint, satisfying "shared across app +
portal."

### Wiring — filter at every send site

Each of the five fan-outs splits its recipient list twice — once for
each channel — and sends email only to the email-enabled subset, push
only to the push-enabled subset. External (non-user) email recipients
have no account, so no preference, and always receive email (they can't
push). Email remains the system of record; push and the new document
email are best-effort.

### New event: `DOCUMENT`

The "Neue Dokumente" category required a brand-new notification. A
post-sync pass (`services/document_notify`) finds freshly-synced
documents of owner-relevant kinds (Jahresabrechnung, Wirtschaftsplan,
Protokoll, Umlaufbeschluss — deliberately **not** Rechnung/Sonstiges to
avoid noise, and not the invitation docs that already notify via
`ETV_INVITATION`) and notifies whoever may *see* each doc — reusing the
exact unit/contract/contact scoping the documents tab enforces, so
"notified" and "visible in your tab" never disagree. Idempotency +
first-run safety come from a `documents.notified_at` column, baselined
to `now()` for the existing backlog in the migration so the first
post-deploy sync can't avalanche.

## Consequences

- **No new infra.** Preferences are a small table; the document pass
  runs inside the existing nightly `sync_all_impower` Celery task as an
  isolated phase (a failure there can't roll back the mirror sync).
- **Push for Mitteilungen + Dokumente is net-new** (both were
  email-only / non-existent before). Still gated on APNs being
  configured — no-ops until the `.p8` is set, like everything else.
- **Granularity is per-category, not per-property or per-document-kind.**
  A single `DOCUMENT` toggle covers all relevant kinds. Finer control
  (e.g. a row per Liegenschaft) can layer on later without an API break
  — the matrix shape stays.
- **Verwalter** are excluded from the per-document push (they manage the
  docs); they still get every other category like any user.

## Alternatives considered

- **JSONB blob on `users`** instead of a table — simpler to write, but
  awkward to filter a recipient list against in SQL. The table makes
  `filter_user_ids` a single indexed query.
- **Opt-in default** — rejected: it would silently switch off everyone's
  existing email at rollout. Opt-out preserves today's behaviour.
- **Per-document-kind toggles** — deferred as noise; the single
  `DOCUMENT` category covers the owner-relevant kinds and keeps the UI a
  clean 5×2 grid.
