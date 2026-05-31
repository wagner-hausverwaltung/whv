# ADR-0014: Document ACL — trust Impower's owner attribution

- Status: Accepted
- Date: 2026-05-31
- Deciders: WHV engineering + operator
- Related: ADR-0013 (RAG assistant), task #153

## Context

The portal/iOS documents tab and the RAG assistant share one access-control
gate: `_document_visibility_filter` in `app/api/v1/me.py` (the assistant reuses
it verbatim through `app/rag/retrieval.py::resolve_caller_scope`). It scopes a
document to a caller via the Impower-mirrored FKs
`unit_id` / `contract_id` / `contact_id`, with one fallback branch: a document
with **all three FKs NULL** is "property-wide" — visible to every member of the
property.

The concern (#153) was that per-owner financial documents
(Hausgeld-/Heizkosten-/Betriebskostenabrechnung) could leak across owners
through that fallback. A read-only prod audit + attribution probe
(`prod-doc-acl-stats`, 2026-05-31, 3309 live documents) tested that:

- **Impower already attributes the individual per-owner documents.** 188/215
  `HOUSE_MONEY_SETTLEMENT` and 122/232 `HEATING_COST_DISTRIBUTION` documents
  carry an owner FK and are correctly scoped today.
- **The 420 property-wide (all-FKs-NULL) documents have *no* owner reference
  in Impower's payload** — `unitId` / `contractId` / `contactId` are all null
  in `raw_jsonb`; only `sourceId` is set (348/420). Nothing is backfillable
  from the document's own owner fields (0 resolvable).
- Of the 142 property-wide documents that are settlement-typed, **32 are named
  `Gesamt*` (whole-WEG aggregates), 0 are named `Einzel*`**, and they share only
  48 distinct `sourceId`s (~3 docs per settlement run — aggregate cardinality,
  not one-per-owner).

Conclusion: Impower leaves the owner FKs empty **only for genuinely WEG-level
documents** (the Gesamtabrechnung / Gesamtwirtschaftsplan every owner is
entitled to see). The feared cross-owner leak does not materialise in the data.

A short-lived fail-closed variant of this ADR (hide every NULL-FK personal-
financial doc from non-Verwalter) shipped to prod on 2026-05-31 and was
**reverted the same day** once the probe showed it over-hides legitimate
Gesamtabrechnungen.

## Decision

**Trust Impower's attribution.** A document with no owner FK is treated as
WEG-level and stays visible to every member of its property; individual
per-owner Abrechnungen are protected because Impower tags them with a
unit/contract/contact FK that routes them through the scoped branches. The
property-wide fallback is therefore kept as-is — no kind/source-type fail-closed
overlay. Verwalter continue to see everything.

## Consequences

- **No over-hiding**: owners keep access to their WEG's Gesamtabrechnung /
  Gesamtwirtschaftsplan and other WEG-level documents.
- **Individual docs stay private** via Impower's own FK attribution (the
  cross-user/cross-property/cross-org red-team in `test_rag_retrieval.py` still
  guards this, plus a new test that a NULL-FK Gesamtabrechnung is visible while
  a contact-scoped doc is not).
- **Residual risk**: if Impower ever ships an *individual* per-owner document
  without an owner FK, it would be property-wide visible. The probe found no
  such case today (0 `Einzel*`, individual settlement docs all FK-attributed).
  The `prod-doc-acl-stats` workflow can re-run any time to re-check.

### Not enforcing the visibility enum

`DocumentVisibility` is 100% the `PRIVATE` server-default in prod and remains
**unenforced** — naively enforcing it would hide everything from owners. It
stays a dead column. If Impower attribution ever proves unreliable, the right
follow-up is an explicit, Verwalter-set visibility (or a `sourceId → settlement
→ owner` resolution to attribute stragglers) rather than reviving the blunt
kind-based fail-closed.
