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

**Still not in v1.2, follow-ups if real-world usage demands**:

- Per-comment edit history (currently only `edited_at` is captured; the prior body is lost). Add an `announcement_comment_versions` table if we ever need to argue with an author about "what they actually wrote".
- Comment-thread digest emails. Currently every comment fires its own notification — sufficient at the v1 volume we expect, but a noisy thread could spam Verwalter. Trivially solvable by switching the per-comment send to a Celery debounce that batches every 10 min.
- iOS surface — `Messages` inbox screen in REQUIREMENTS.md §8.3 maps to this domain; binding will happen in the Phase 2 iOS scaffold.

## v1.1 follow-ups (shipped 2026-05-25)

Five extensions landed the same day as v1.0:

1. **Comment edits** — `announcement_comments.edited_at` + author-only `PATCH /me/announcements/{id}/comments/{cid}`. Admin can't edit user content (separate moderation surface). Portal renders a "bearbeitet" indicator + inline edit form with pencil icon on own rows.
2. **Cross-property admin queue** — `GET /admin/announcements` + new top-level nav entry → `AdminAnnouncementsAllPage`. Filter chips (`?status=all|scheduled|published`) + property column on each row. Compose still happens per-property tab to keep the scope-target obvious.
3. **Comment notifications** — On every `POST /me/announcements/{id}/comments` commit, fan out to (Verwalter team for the org) ∪ (prior non-hidden commenters on the thread), excluding the new commenter. Hidden commenters explicitly don't get re-pinged — moderated-out users shouldn't keep receiving thread updates. Failures are caught + logged WARN; the comment commit stands.
4. **Per-recipient send-attempt log + manual resend** — New `announcement_send_attempts` table (append-only). The Celery publish task and the manual resend both write one row per recipient (SUCCESS / FAILED + error_message). Admin SPA renders a "Zustellprotokoll" panel under the detail page with status chips + an "Erneut senden (N)" button that hits `POST /admin/announcements/{id}/resend-failed`. The retry resolves recipients as "latest attempt per email is FAILED" — a row that previously failed but later succeeded drops out of the retry set on its own.
5. **Per-unit recipient narrowing** — New `announcement_units(announcement_id, unit_id)` junction. Empty set = property-wide-by-role (no behaviour change for v1 callers, backwards compatible). Non-empty = the audience-role filter is intersected with `Contract.unit_id IN (target_set)`, so e.g. only Mietern of unit 3a + 4b get the Aufzug-Wartung notice. The admin SPA Autocomplete picker in both compose + edit forms loads the property's units once and chooses a subset; a `{count} Einheit(en)` chip on list rows surfaces the narrowing at a glance.

**Decisions made during v1.1 (not pre-planned in v1.0 spec)**:

- **Comment notification recipients**: Verwalter + prior commenters, not just the Verwalter. Threads on a Mitteilung tend to involve a small handful of owners; pinging prior participants keeps the back-and-forth visible to them without forcing a portal check. Trade-off: a noisy thread spams; debounce is the easy follow-up (see "Not in v1.1" above).
- **Resend retry mode**: manual button, not auto-backoff. Auto-retry on transient failures sounds appealing but the failure mode we actually see (invalid recipient address, bounced domain) is permanent — auto-retry on those is throwing requests into a void. Manual gives the admin a chance to fix the address or drop the recipient before retrying.
- **Per-unit targeting model**: rows in a junction table, not a denormalised array column on the announcement. Junction makes the SQL trivially-correct (`Contract.unit_id IN subquery`) and gives us a future-friendly model if we need per-unit visibility checks on the portal side too. Costs one extra INSERT-per-unit on save; negligible at v1 scale.
- **Send-attempt log is append-only**: Each retry writes a new row, the original FAILED stays. "Latest attempt per recipient" resolves via timestamp. Simpler than mutating rows, and the audit trail captures the sequence ("failed at 9:00, retried at 9:05, succeeded at 9:30") — useful for figuring out whether a slow bounce is from a transient outage or a permanent block.

## v1.2 follow-ups (shipped 2026-05-25)

One extension landed shortly after v1.1, prompted by a real-world bug: a Mitteilung composed for `MV Hohewartstraße 13, 70469 Stuttgart` published correctly but reached zero recipients, because the staging DB had only one user account (the Verwalter) and zero portal accounts attached to the property's contracts. `resolve_recipients` returned `[]`, the Celery task marked the row published with a WARN, and there was no admin surface that made the empty audience visible. The user reported "I don't see the Mitteilung on the property in the end-user portal" — by design (Verwalter is excluded from the audience), but the deeper issue is that there were no eligible portal users to receive it.

The fix is a **per-Mitteilung recipient editor** that lets the admin both see the resolved set and override it. Three pieces shipped:

1. **`excluded_user_ids` + `extra_emails` columns** on `announcements`. Both Postgres array columns, default `'{}'`, NOT NULL. The auto-resolved set (audience role + per-unit filter) stays the baseline; `excluded_user_ids` is a deny-list against it, `extra_emails` is a free-text add-list for non-portal recipients. The final send set on every fan-out = `(auto_users − excluded) ∪ extras`, re-resolved on every send so new portal users joining the property automatically get future fan-outs.

2. **Recipient-preview endpoint** `GET /admin/announcements/{id}/recipient-preview` returns the auto-resolved users (with each row flagged as `excluded=true/false`) + the extra emails + the resolved `active_emails` list the next send would actually fan out to. Admin SPA renders this as a checkbox list (auto-resolved) + a chip list with an add-form (extras) + a Save button that PATCHes both arrays.

3. **General `/resend` replaces `/resend-failed`**. The v1.1 button retried only addresses whose latest attempt was FAILED; v1.2 sends to the *current active set* regardless of prior outcome. The mental model shifts from "retry transient failures" to "the audience just changed (or I just typed a new email), redo the fan-out". An admin who's hit Resend's 100-email free-tier cap can throttle by unchecking most recipients, saving, then resending to just the few they care about.

**Decisions made during v1.2**:

- **Override model**: auto + excludes + extras, not full manual override. New portal users joining the property after the Mitteilung publishes should automatically be in the next resend; a full manual override would freeze the recipient list at the moment of first edit and require admin re-touch every time the property changes. The few-extras-on-top-of-auto model handles the realistic case (a Hausmeister or external contractor with no portal account who needs the notice).
- **`/resend` semantics**: replaces failed-only-retry, doesn't coexist with it. Two buttons for "subset retry" and "full resend" is admin-cognitive-load we don't need at v1 volume. If "retry failed only" becomes a real need later (high-volume Hausverwaltung sending Mitteilungen to thousands), bring back a `?failed_only=true` query param.
- **No "preview as owner" affordance**: the admin sees the active recipient list directly. We considered a "see what an Eigentümer of unit 3a would see" toggle but rejected it — the active-emails count + per-row check states already answer "did I reach the right people?".

**Still not in v1.2**:

- Same three carry-overs as before (per-comment edit history, comment-thread digest, iOS Messages screen).
- Rate-limit feedback in the SPA. When Resend rejects with 429 (free tier 100/day), the per-recipient FAILED row captures it but the toast doesn't distinguish "rate-limited" from "permanent failure". A v1.3 polish would parse the error code and show "Tageslimit erreicht — bitte Plan upgraden" with a doc link.

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
