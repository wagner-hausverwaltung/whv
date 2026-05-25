# ADR-0007: Eigentümerversammlung — tally on agenda item, signed PDF as record of truth

Date: 2026-05-25
Status: Accepted

## Context

WEG-Recht distinguishes two ways an Eigentümergemeinschaft makes
decisions:

1. **Umlaufbeschluss** — written-circular vote, no meeting required.
   Every vote is recorded as an explicit click in the portal; the
   click stream IS the authoritative record.
2. **Eigentümerversammlung (ETV)** — in-person (or hybrid) assembly,
   typically annual. The Verwalter writes a **signed protocol PDF**
   that records what was decided. The protocol is the authoritative
   record; the portal merely transcribes it for searchable display.

We already shipped the circular case as `circular_resolutions` +
`circular_votes` (ADR-implicit; see `app/models/circular.py`). This
ADR covers the ETV side. The user asked for full-stack ETV support
on 2026-05-25 ("create a new tab where the users see the details of
all past and planned ETV") — including the iOS reading surface.

## Decision

Three new tables form a strict tree:

```
etv_assemblies            (one row per scheduled assembly)
  └── etv_agenda_items    (one row per Tagesordnungspunkt — TOP)
        └── etv_discussion_entries  (per-TOP discussion log)
```

### Why tally lives on the agenda item, not in a votes table

For an Umlaufbeschluss we needed a `circular_votes` row per owner per
resolution: the owner clicks a button and that click *is* the vote.

For an ETV, the owner does not vote in the portal — they raise their
hand in the room. The Verwalter transcribes the result into the
**signed protocol PDF** and we mirror those numbers into the row.
Storing `vote_yes / vote_no / vote_abstain` as integer columns on
`etv_agenda_items` is the simplest faithful representation:

- The protocol is the legal record; the database row is the searchable
  shadow. A `votes` row-per-owner table would imply we know which
  owner voted which way, which we don't (and shouldn't claim — the
  protocol records aggregate counts, not per-owner choices, unless
  the WEG explicitly resolved otherwise).
- The aggregate format matches what `circular_resolutions.result` is
  already storing ("12 JA, 1 NEIN, 0 Enthaltung → angenommen"), just
  decomposed into three integers + an explicit `vote_result` enum
  rather than free-text.
- It keeps reads cheap. The owner detail endpoint hits one row per
  agenda item, no aggregations.

### Status lifecycle

```
GEPLANT  ──invitations sent──→  EINGELADEN
                                    │
                  actual meeting    │
                                    ▼
                              ABGEHALTEN  ←──── protocol PDF uploaded
                                    │
                                    │ (terminal — read-only after this)
                                    ▼

   any state may go to:  ABGESAGT  (terminal, hidden from owners)
```

The status is moved manually by the Verwalter — there's no time-based
auto-flip (unlike `circular_resolutions`, which closes at `closes_at`).
The owner-portal view filters out ABGESAGT entirely; the admin view
shows it.

### Soft-delete

`etv_assemblies.deleted_at` allows the Verwalter to retract an
assembly without breaking history. Soft-deleted rows are invisible
to both owner + admin reads. Agenda items + discussion entries do NOT
have their own soft-delete column — they're hard-deleted (CASCADE on
the parent), since they're authored entirely by the Verwalter and
have no third-party-visible audit trail concern.

### Protocol PDF storage

Mirrors the `announcement_attachment` pattern (ADR-0006):

- Local disk under `settings.etv_protocol_dir` (default
  `/var/lib/whv/etv-protocols/`).
- Filename `{assembly_id}.pdf` so re-uploads cleanly overwrite.
- 50 MB cap (`etv_protocol_max_bytes`) — same as documents, generous
  enough for protocols with photo appendices.
- Served via authenticated `FileResponse` on
  `GET /me/assemblies/{id}/protocol` — the scope check runs on every
  fetch, so a leaked URL alone doesn't expose the file.

### Endpoint shape

Owner side (read-only — the protocol is the record, not the click
stream):

```
GET  /me/properties/{pid}/assemblies      list (no ABGESAGT)
GET  /me/assemblies/{id}                  detail with full agenda
GET  /me/assemblies/{id}/protocol         PDF download
```

Admin side (Verwalter-only):

```
POST   /admin/properties/{pid}/assemblies         create
GET    /admin/properties/{pid}/assemblies         list (includes ABGESAGT)
GET    /admin/assemblies                          cross-property queue
GET    /admin/assemblies/{id}                     detail
PATCH  /admin/assemblies/{id}                     edit header
DELETE /admin/assemblies/{id}                     soft-delete
POST   /admin/assemblies/{id}/agenda-items        add TOP
PATCH  /admin/agenda-items/{id}                   edit TOP (incl. tallies)
DELETE /admin/agenda-items/{id}                   remove TOP
POST   /admin/agenda-items/{id}/discussion        add discussion entry
DELETE /admin/discussion/{id}                     remove entry
POST   /admin/assemblies/{id}/protocol            upload signed PDF
```

The `(assembly_id, position)` UNIQUE constraint on `etv_agenda_items`
(and the same on `etv_discussion_entries.agenda_item_id, position`)
means re-ordering is two PATCH calls — there's no native bulk
reorder yet. If reordering becomes a hot path we'll add a single
endpoint that takes `[{id, position}]` and applies them in one
transaction.

### Per-TOP type discriminator

`AgendaItemType` is one of `INFORMATION | BESCHLUSS | DISKUSSION`:

- INFORMATION rows have no `beschluss_text`, no tally fields. UI hides
  the vote pane.
- BESCHLUSS rows are the ones the protocol cares about — they carry
  `beschluss_text` (the verbatim resolution wording) + tally + result.
- DISKUSSION rows have a long-form discussion log but no vote. UI
  shows only the speaker contributions.

`vote_required_quorum` is NULL by default; the field exists for
BESCHLUSS items that need a minimum cast-count to be valid (matches
the `circular_resolutions.required_quorum` convention). If
`(vote_yes + vote_no + vote_abstain) < required_quorum`, the result
is automatically ABGELEHNT (mirrors the circular tally helper).

Both the schema-level validator and the API enforce that
`beschluss_text` and `vote_required_quorum` are NULL on non-BESCHLUSS
rows. We keep the rule in the application layer rather than as a
DB-level CHECK because the rule pivots on an enum value, and we
prefer the validator to live next to the Pydantic schema so the
admin SPA gets a useful 422 message.

### iOS reading surface

The iOS owner app gets a dedicated **Versammlungen** tab between
Tickets and News. Two sections — Geplant / Vergangen — sorted by
`scheduled_start`. Tapping a row opens a single-scroll detail view:

```
[Status chip]  [Protokoll vorhanden]
TITLE
📅 date · 📍 location

Beschreibung

Tagesordnung
  TOP 1 — INFORMATION — Begrüßung …
  TOP 2 — BESCHLUSS    — Jahresabrechnung 2024  [ANGENOMMEN]
    Beschlusstext: …
    Ja: 13   Nein: 0   Enth.: 1
    Diskussion:
      Herr Müller (WE 4): …
      Frau Wagner: …
  …

Signiertes Protokoll
  [📄 Protokoll als PDF öffnen — hochgeladen am DD.MM.YYYY]
```

The Phase 2 scaffold ships with baked-in demo assemblies in
`DemoAssemblies.swift` so the layout renders even before a real
account is signed in. Phase 2.1 swaps the source for a live
`/me/properties/{id}/assemblies` fetch — the view layer stays
identical because Assembly + AgendaItem are already Codable shapes
matching the backend response.

## Consequences

### Positive

- One schema migration adds the whole feature; no follow-ups needed
  for tallies, discussions, or protocol upload.
- The data model maps 1:1 to what the Verwalter actually writes in
  the protocol — the admin SPA's "edit TOP" form has the same fields
  as the protocol's TOP section.
- The owner side stays trivially cacheable — a single nested GET
  returns the whole tree. No per-row authorization checks because
  scope is enforced at the property level.

### Negative

- We can't tell from the database alone whether a BESCHLUSS was a
  named-vote or aggregate-only. If a WEG ever needs per-owner records
  for a specific resolution, we'd need a new optional
  `etv_assembly_votes` table. The current shape doesn't paint us into
  a corner — we'd just add the table when needed.
- No native reorder endpoint. Moving TOP 3 above TOP 2 requires two
  PATCH calls that swap positions, which means the SPA has to
  serialize them — a transient state could violate the UNIQUE
  constraint mid-swap. Acceptable for v1 because reordering is rare;
  add a bulk endpoint if it becomes a friction point.

### Follow-ups (post-v1)

- Email-invite-with-`.ics` flow when status transitions to EINGELADEN
  (mirrors the circular invitation email).
- Per-owner vote ledger (`etv_assembly_votes`) for WEGs that opt into
  named voting.
- Bulk-reorder endpoint for agenda items.
- iOS PDF preview via QuickLook when the user taps the protocol
  link (Phase 2.1).
- Universal Link from email → iOS assembly detail (Phase 2.2,
  blocked on Apple Developer enrollment / DUNS).

## Alternatives considered

**Reuse circular_resolutions** — would require adding `scheduled_start`,
`scheduled_end`, `location`, `protocol_pdf_url`, plus agenda + discussion
child tables. The resulting schema mixes two governance modes whose
state machines + audit needs diverge over time. Cleaner to keep
"circular" and "in-person" separate.

**No tally fields, only a protocol PDF** — viable, but then the iOS UI
can only show "Beschluss angenommen / abgelehnt" by parsing the PDF
or relying on a free-text `result` column. Integer tally fields let
the iOS UI render charts, comparisons across years, etc. without
PDF parsing.

**Separate `etv_protocols` table** — overkill. A single optional
`protocol_pdf_url` column on the assembly row covers the one-PDF-per-
assembly invariant and matches how the Verwalter actually thinks
about it ("the protocol of this meeting").
