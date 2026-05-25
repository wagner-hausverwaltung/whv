# ADR-0006: Announcements (Mitteilungen) — schema, editorial delay, moderation

- Date: 2026-05-25
- Status: Accepted
- Resolves: REQUIREMENTS.md §10.8 (Announcements / Mitteilungen)
- Touches: `backend/app/models/announcement.py`, `backend/app/services/announcements.py`, `backend/app/api/v1/announcements.py`, `backend/app/workers/tasks.py`, `web/src/components/AdminAnnouncementsTab.tsx`, `web/src/admin/pages/AdminAnnouncementDetailPage.tsx`, `web/src/pages/MyAnnouncements*.tsx`

## Context

Wagner Hausverwaltung wants a way to push property-wide messages — outage notices, Beirat updates, scheduled Wartungen, "die Hofeinfahrt wird morgen asphaltiert" — to all relevant owners / tenants / Beiräte in one shot, with attachments (a PDF protocol, a photo of the damage notice) and a comment thread so questions don't fan out into separate emails. The existing Ticket system covers 1:1 + small-group conversations; resolutions cover formal votes; neither is the right shape for a 1-to-many bulletin.

The closest off-the-shelf analog is a tenant-association noticeboard: many recipients, low volume per property, often time-sensitive, occasionally needs editorial polish before the email actually goes out ("oh wait, that's the wrong start time"). Building this on top of the existing tickets table would have mangled the semantics (a ticket has a single thread, an explicit creator, status transitions) and made the audience-filter logic uglier than starting fresh.

Four design choices drove the schema and the UX. The decisions were locked with the user before any code landed (interactive Q&A, 2026-05-25).

## Decision

### 1. Audience as three booleans on the row, not a join table

`announcements.audience_eigentuemer`, `audience_mieter`, `audience_beirat`, all NOT NULL, defaulted `true`. A DB CHECK enforces at-least-one-true; an API-level validator + service-layer resolved-state check enforce it for create + patch. The publish task filters property participants whose `User.role` matches one of the truthy flags.

**Why not** `announcement_audience(announcement_id, role)` as a junction table:

- The audience is fixed at 3 values (matches the 3 non-VERWALTER `UserRole`s). A junction table buys flexibility we will never use.
- Booleans are queryable inline (`WHERE audience_eigentuemer`) without a join — both the publish task and the portal list filter use these columns directly.
- Post-publish audience edits land in one UPDATE; with a junction we'd need to diff old vs. new memberships.

**Why not** a Postgres `text[]` of role names:

- No type safety; nothing stops an admin from inserting `"vermieter"` (sic) and ending up with a row that never fans out.
- `WHERE 'EIGENTUEMER' = ANY(audience)` is fine but harder for query planners than the boolean form.

### 2. 10-minute editorial buffer with each-save-resets-the-clock

`scheduled_publish_at = now() + 10 min` on create. Every PATCH while unpublished bumps it to `now() + 10 min` again. The Celery beat task (1-min cadence) picks up rows where `scheduled_publish_at <= now() AND notification_sent_at IS NULL AND deleted_at IS NULL`.

The 10-min number is the user's call — long enough to catch a typo or fix the date, short enough that the admin doesn't forget the message is queued. Tied to a partial index (see §3) so the scan stays cheap.

**Alternatives considered**:

- **Fixed timer from creation, no reset on edit.** Predictable, but the obvious failure mode is the admin still typing at minute 9, message goes out half-finished. Mitigated by a "Sofort veröffentlichen" + "Verschieben um 10 min" pair of buttons. Rejected for ergonomics — admin shouldn't have to think about the clock to take a phone call mid-compose.
- **Manual "Verschieben um +10 min" button only, no auto-reset.** Forces the admin to think about the clock explicitly. Rejected as friction.
- **No buffer at all (send-immediately default + "schedule for…" option).** Matches WhatsApp / Slack send semantics. Rejected because the Hausverwaltung's whole value-add is being correct — a typo'd Mitteilung reaches every owner and is much harder to retract than a typo'd Slack message.

The chosen approach pairs naturally with **post-publish editability**: edits after publish bump `updated_at` but don't shift `scheduled_publish_at` (which by then equals the actual fan-out time). The portal renders "bearbeitet am …" when `updated_at > notification_sent_at + 60s` (the 60s grace absorbs the trivial bump from `mark_published` itself).

### 3. Partial index on the publish-due predicate

```sql
CREATE INDEX ix_announcements_due_for_publish
  ON announcements (scheduled_publish_at)
  WHERE notification_sent_at IS NULL AND deleted_at IS NULL
```

The Celery beat scans this index every minute. Once a row publishes or gets soft-deleted, it drops out of the index. So the scan is O(due-rows), not O(total announcements ever). At 100 announcements / month / WHV the full-table scan would also be fine; the partial index is a "free to add now, never have to revisit" move that lets us comfortably scale to 100 customers without a follow-up migration.

### 4. Hide-only comment moderation with full audit trail

`announcement_comments.is_hidden bool DEFAULT false` + `hidden_at`, `hidden_by_user_id`, `hidden_reason` (nullable). Owner reads filter `is_hidden = false`; admin reads include hidden rows with a "verborgen" indicator. Setting `is_hidden = false` clears the audit fields.

**Why not hard-delete**: an aggressive admin clicking "delete" on a slightly-edgy comment that the author then asks about has no defensible answer. Hide preserves the audit trail; the author sees their comment vanished but the row + `hidden_reason` survive in the DB for any later "why was my comment removed" conversation. The admin can un-hide if the moderation was wrong.

**Why not soft-delete via deleted_at**: hidden is a moderation state, not a row-lifecycle state — confusingly overloaded if we used the same column. The audit-trail fields specifically capture moderation actions; a generic `deleted_at` wouldn't.

### 5. Plain-text body, no Markdown

The body is rendered with `white-space: pre-wrap` and no parsing. Matches the ticket-message convention. No XSS surface, no "why isn't my **bold** rendering" support requests, no need to ship a Markdown editor in the SPA. If owners start asking for richer formatting, the next step is a small allowlist (bold, italic, link) not the full CommonMark surface.

### 6. Per-recipient send, no BCC

The fan-out task issues one Resend `POST /emails` per audience-matched user. BCC-style "one send with N hidden recipients" would leak addresses across property participants in any client that surfaces full envelope headers, and we lose per-recipient bounce tracking. We trade an extra HTTP request per recipient for the safety + auditability. At realistic volumes (≤ 100 recipients per Mitteilung, ≤ a few Mitteilungen / week) the extra latency is invisible.

### 7. Mark-published before the send loop (idempotency)

`mark_published(announcement)` stamps `notification_sent_at = now()` and commits **before** the per-recipient send loop. The row immediately drops out of the publish-due partial index, so a Resend hiccup or worker restart can't double-send next tick. Failure mode: every recipient send fails → admin sees a "published" row with no actual emails delivered. The per-recipient `EmailError` is logged WARN-level so the next deploy smoke catches it. Acceptable trade — "published but emails failed" is a known-recoverable state we can address with a `/admin/announcements/{id}/resend` button if it ever happens in practice.

## Status / scope

In production on staging from 2026-05-25. 19 backend tests (lifecycle, scope, audience, moderation, fan-out idempotency) all passing. Admin SPA tab + detail page live on `staging.admin.wagner-hausverwaltung.com`; portal list + detail on `staging.portal.wagner-hausverwaltung.com`.

**Not in v1, follow-ups if real-world usage demands**:

- Comment edits (currently: post a follow-up). Adds an `edited_at` column and an "edit" toggle on each owner's own comment.
- Comment notifications (admin sees new comments in the SPA; users see them on next open). Adds Celery batching ("digest of new comments on Mitteilung X").
- Cross-property admin "Alle Mitteilungen" queue. Currently per-property only; bolt on when the WHV manages enough properties that this becomes painful.
- Resend-failed-recipients button. Stub until we see a real bounce.
- iOS surface — `Messages` inbox screen in REQUIREMENTS.md §8.3 maps to this domain; binding will happen in the Phase 2 iOS scaffold.

## Consequences

Pro:

- **Editorial buffer prevents a real failure mode** (typo'd notices reaching every owner) without adding admin friction.
- **Audience model is queryable in plain SQL**, no join, no array-contains predicates.
- **Idempotent fan-out** by construction — re-running the beat task is safe at any point.
- **Audit trail** for both the announcement itself (AuditLog) and individual comment moderation (`hidden_*` fields).
- **Reuses existing patterns** end-to-end: same storage convention as `ticket_attachments`, same Resend client, same per-property scope rules, same MUI list/detail SPA shape.

Con:

- The audience design **can't easily express "this announcement is only for owners of unit 3"** — that needs an explicit recipient list. If the user starts wanting per-unit targeting, we'll add an optional `announcement_recipients` table that overrides the role flags. Out of scope for now; the role-level filter has covered every concrete use case the user raised.
- **No comment notifications in v1** — power users may want them. Easy to add later; not free in the comment moderation UX (do hidden-then-unhidden comments re-notify? probably no, but the spec needs to be explicit).
- **Plain-text body** means a hyperlink in a Mitteilung is shown literally (`https://…`). The portal could auto-linkify on display; out of scope for v1.
