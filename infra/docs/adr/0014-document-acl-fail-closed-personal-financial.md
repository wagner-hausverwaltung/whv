# ADR-0014: Fail closed on unattributed personal-financial documents

- Status: Accepted
- Date: 2026-05-31
- Deciders: WHV engineering
- Related: ADR-0013 (RAG assistant), task #153

## Context

The portal/iOS documents tab and the RAG assistant share one access-control
gate: `_document_visibility_filter` in `app/api/v1/me.py` (the assistant reuses
it verbatim through `app/rag/retrieval.py::resolve_caller_scope`). The gate
scopes a document to a caller via the Impower-mirrored FKs
`unit_id` / `contract_id` / `contact_id`. Its first branch made a document with
**all three FKs NULL** visible to *every* member of the property ("property-wide").

That fallback is wrong for documents that are inherently personal to a single
owner/tenant. A `prod-doc-acl-stats` read-only audit (2026-05-31, 3309 live
documents) quantified the leak:

| kind | total | property-wide (all FKs NULL) |
|---|---:|---:|
| JAHRESABRECHNUNG | 475 | **137** |
| SONSTIGES | 1440 | 257 (incl. 5 `SPECIAL_CONTRIBUTION`) |
| RECHNUNG | 1175 | 0 |
| WIRTSCHAFTSPLAN | 211 | 26 |

By Impower source type, the property-wide leak was concentrated in
`HEATING_COST_DISTRIBUTION` (110), `HOUSE_MONEY_SETTLEMENT` (27) and
`SPECIAL_CONTRIBUTION` (5) — i.e. Heizkosten-/Hausgeldabrechnungen and
Sonderumlagen, each of which names another owner/tenant and their amounts.
**137 Jahresabrechnungen were visible across owners.** The
`DocumentVisibility` enum exists but is **unenforced** — every one of the 3309
rows is the `PRIVATE` server-default, so the enum carries no usable signal and
cannot be naively enforced (doing so would hide everything from owners).

## Decision

Narrow the property-wide branch: a document with no owner FK is property-wide
visible to non-Verwalter callers **only if it is not personal-financial**. A
document is personal-financial when:

- `kind == JAHRESABRECHNUNG` (covers the Hausgeld-/Heizkosten-/
  Betriebskostenabrechnungen synced from Impower), **or**
- `impower_source_type ∈ { HOUSE_MONEY_SETTLEMENT, HEATING_COST_DISTRIBUTION,
  OPS_COST_REPORT, RENT_SETTLEMENT_EXCHANGE, SPECIAL_CONTRIBUTION }` (catches
  the few — e.g. Sonderumlage — that the kind mapping files under SONSTIGES).

Such a document, when it arrives without an owner FK, is **hidden from every
non-Verwalter** (fail closed) until a Verwalter files the unit/contract/contact
that attributes it — at which point the existing unit/contract/contact branches
let the right owner, and only them, see it. Verwalter continue to see
everything. The predicate is NULL-safe (`impower_source_type IS NOT NULL` guard)
so ordinary docs with no source type stay shareable.

Because the change lives in the single shared gate, it applies identically to
the documents tab and the assistant. Guarded by
`test_caller_scope_hides_unattributed_personal_financial_docs`.

## Consequences

- **Closes the known PII leak** (≈142 documents) on both surfaces immediately,
  with no schema change and no migration.
- **No over-hiding**: genuinely WEG-wide documents stay visible to owners —
  Wirtschaftsplan (`ECONOMIC_PLAN`), the general ledger (`ACCOUNTING_EVENT`),
  Gewinn-/Verlustrechnung (`PROFIT_AND_LOSS`), plain Sonstiges.
- **Recoverable false positives**: filing the owner FK in Impower (or manually)
  restores access to the correct owner. The worst case is "an owner can't yet
  see their own Abrechnung in the portal," not a cross-owner leak.

### Residual risk (accepted for the stopgap)

- NULL-FK documents with source type `ACCOUNTING_EVENT` (136), `EXCHANGE` (47)
  or none (66) remain property-wide. They are plausibly WEG-shared; blanket
  hiding them would regress the product. They are *not* the known leak.
- The `DocumentVisibility` enum stays unenforced (dead column).

### Full fix (follow-up, not in this stopgap)

1. Backfill owner FKs from Impower `unitId` / `contractId` / `contactId` for the
   existing corpus so personal documents are attributable, not NULL-FK.
2. Make "property-wide" an **explicit** visibility a Verwalter sets, not an
   all-NULL fallback; populate and enforce `DocumentVisibility`.
3. Re-classify financial documents currently landing as SONSTIGES.
