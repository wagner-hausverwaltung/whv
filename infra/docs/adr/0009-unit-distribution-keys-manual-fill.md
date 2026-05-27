# ADR-0009 — Unit distribution keys are manual-fill, with a browser-extension upgrade path

**Status:** accepted
**Date:** 2026-05-27
**Deciders:** Luis Wagner

## Context

Impower's "Eigenschaften der Einheiten" panel (section 7 on the property masterdata screen) holds four cost-distribution values per unit:

- **MEA** (Miteigentumsanteil) — fraction-of-total ownership share. Only meaningful for WEG / SEV properties; rentals (MV) leave it blank.
- **Fläche (m²)** — usable floor area.
- **Heizfläche (m²)** — heating floor area (excludes terraces, often differs from Fläche).
- **Personen** — registered head-count for cost distribution. Numeric, not integer — Impower allows 0.5 partials for shared apartments.

These are the master-truth values WHV needs on every unit detail screen across iOS, the owner portal, and the admin SPA — they're what Verwalter cite in invoices, Wirtschaftspläne, and Jahresabrechnungen.

**The gap:** I pulled the live OpenAPI spec from `api.prod-replica.develop.impower.de/v2` and inventoried all 67 endpoints. None of them expose these values:

- `GET /v2/units` and `GET /v2/units/{id}` both return a bare `UnitDto` containing only `id, propertyId, unitHrId, floor, position, type, unitRank, isOwnedByWeg, created, updated`.
- `GET /v2/properties/{id}` returns a `PropertyDto` with no embedded distribution-keys array either.
- No `/distribution-keys`, `/unit-characteristics`, or `/unit-properties` endpoint exists.
- `HeatingCenterUnitDto` (the closest candidate) only carries `heatingCenterId, unitId, checked, mscUnitId, domainId` — no area.

So the data is real (it renders in Impower's UI) but **the Impower public REST API does not currently expose it.**

## Decision

Ship a **two-phase** solution:

### Phase A — manual-fill (this commit)

- Add `heated_area_m2` and `persons` columns to `units` alongside the existing `voting_share` and `area_m2`. All four are nullable Decimal.
- Backend exposes `PUT /admin/units/{id}/distribution-keys` for Verwalter-driven updates with audit-log capture (`action="unit.distribution_keys.updated"`).
- Admin SPA `/admin/units` table renders the four values plus an edit button per row; dialog hides MEA on MV properties.
- Portal `/properties/:id` + iOS PropertyDetailView render the four metrics with the same WEG/SEV-only gate for MEA.
- Property `type` (`OWNER` / `RENTAL` / `STRATA` from Impower) is already synced; we add `propertyTypeLabel()` / `Liegenschaft.typeLabel` helpers to render it as `WEG` / `MV` / `SEV` — the German correspondence labels Wagner already uses.

### Phase B — browser-extension auto-fill (planned, not blocking)

A Chrome/Edge/Firefox extension that activates on `*.impower.de/*`. Mechanics:

1. **Content script** watches for the `data-testid="section-DistributionKeys"` panel.
2. **DOM scrape** the table rows — Impower's React app puts the values into `<input value="...">` even on the read-only view, so a `querySelectorAll('.ant-table-row')` walk gives us cell-by-cell access. Each row's `data-row-key` is Impower's internal unit id, which we mirror as `units.impower_id` server-side.
3. **POST** the bulk payload to a new admin endpoint `POST /admin/properties/{id}/unit-distribution-keys/import` accepting `[{impower_unit_id, voting_share?, area_m2?, heated_area_m2?, persons?}, …]`.
4. **Trigger** = button injected next to the section header ("Zu WHV synchronisieren"). Auto-fire is avoided so the operator stays in control.

This is a Phase B follow-up because (a) the columns and endpoint need to exist first, and (b) the extension involves CSP / publishing gymnastics that shouldn't block the user from typing values today.

## Consequences

- **Data hygiene risk:** humans transcribe values from one screen to another. Mitigations: the admin dialog hides MEA when it doesn't apply, the audit log captures every change, and the eventual browser extension eliminates the typing.
- **No silent drift:** we don't reconcile against Impower for these four columns (we can't — Impower doesn't expose them). If a Verwalter updates MEA in Impower without re-entering it on our side, our value will be stale until the extension lands or someone re-enters it.
- **One-way write:** the manual editor (and the future extension) only write to our side. We never write back to Impower — they remain the system of record per the working agreement "data in impower must never be deleted".
- **Friction is intentional:** until Impower exposes the panel, every WEG / SEV property needs a one-time master-data setup pass by the Verwalter. The admin SPA flags this with an info banner on the Einheiten page.

## Alternatives considered

- **Email Impower asking them to expose the endpoint.** Right long-term play; left as a separate request, but doesn't unblock today.
- **HTML scraping from the backend.** Would need an Impower user session, runs counter to their tenancy model, and breaks the moment Impower changes their React render. Rejected.
- **Always render an empty MEA column.** Considered, but on MV properties the column reads as "unset values" rather than "doesn't apply" — confusing to owners scanning the portal. WEG-only gating reads as honest.
