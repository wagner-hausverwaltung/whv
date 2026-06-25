# ADR-0018 — Liegenschafts-Kalender (events + ETV + WHV-design PDF)

**Status:** accepted
**Date:** 2026-06-24
**Deciders:** Luis Wagner

## Context

Owners + Verwalter want a per-property calendar: the ETV date(s) highlighted,
plus the recurring duties the Verwalter assigns — **Winterdienst** and
**Kehrwoche** — handed to a specific owner, plus generic Termine. A printable
PDF in WHV design to post in the Hausflur would be nice.

## Decision

### Stored events + derived ETV (never store ETV twice)

- `calendar_events` — Verwalter-created, per property: `event_type`
  (WINTERDIENST / KEHRWOCHE / TERMIN), optional `title` (defaulted from the
  type), `starts_on` + optional `ends_on` (a Kehrwoche week is a range),
  `assigned_user_id` (so the portal/app can highlight "your duty" for the
  logged-in owner) **and** `assigned_label` (free-text name for owners
  without an account / a unit / an external party), `note`.
- **ETV dates are NOT stored here.** The merged read view derives them live
  from `etv_assemblies` (non-cancelled, scheduled in the window), so they can
  never drift from the assembly record. Each merged entry carries `source`
  ("event" = editable, "etv" = read-only) and, for ETV, the `assembly_id` for
  a deep link.

### Surfaces

- **Member** (read-only): `GET /me/properties/{id}/calendar?year&month` —
  merged month view.
- **Admin**: same merged view + event CRUD
  (`POST /admin/properties/{id}/calendar/events`,
  `PATCH/DELETE /admin/calendar/events/{id}`) + a **WHV-design month-grid
  PDF** (`GET …/calendar.pdf`) that reuses the assembly-PDF chrome and lists
  the assignments under the grid for handing out.

### v1 scope decisions

- **Discrete assignments**, not auto-rotation — the Verwalter picks the owner
  + date/week per entry. A weekly Kehrwoche-rotation generator is a possible
  later enhancement.
- The PDF is a **month grid + assignment list**; rendered on demand (streamed,
  not persisted).

## Consequences

- Member access reuses `_visible_properties_stmt`; cross-org isolation is
  covered by a test.
- Deleting an assembly automatically removes its calendar appearance (it was
  never stored) — no cleanup job.
- The month PDF reuses `assembly_document`'s header/logo, so it reads as the
  same brand as the Protokoll + Vollmacht.

## Alternatives considered

- **Store ETV as calendar rows** — rejected: they'd drift when an assembly is
  rescheduled/cancelled; deriving live is always correct.
- **Weekly Kehrwoche auto-rotation** — deferred; discrete entries cover the
  need and avoid guessing the rotation order/holidays for v1.

## Update — .ics export (2026-06-25)

Members can export a property's whole calendar as an iCalendar file for
Outlook / Apple Calendar / Google: `GET /me/properties/{id}/calendar.ics`
(`app/integrations/calendar_ics.py`, hand-rolled RFC 5545, no extra dep). ETV
assemblies export as **timed** VEVENTs (real `scheduled_start/end`, `LOCATION`,
Teams URL); Winterdienst/Kehrwoche/Termin as **all-day** VEVENTs. Stable UIDs
(`etv-<id>@…` / `event-<id>@…`) so a re-import updates rather than duplicates.
Portal: download button on the Kalender tab. iOS: share-sheet from the Kalender
sheet ("Add to Calendar" / send to Outlook). One-shot download (no subscription
feed) — no standing tokenised exposure of calendar data.
