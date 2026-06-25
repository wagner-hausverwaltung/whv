# Offer base templates (anfragen@ auto-offer, ADR-0017)

Blanked, PII-free base PDFs the offer generator stamps per-customer values onto
(`app/integrations/pdf/offer_document.py`).

- **`weg_template.pdf`** — the VDIV Deutschland / Haus & Grund Deutschland
  *Verwaltervertrag für Wohnungseigentumsanlagen* (April 2022 Mustervertrag),
  used by WHV as a VDIV member/licensee. Derived from a real filled offer with
  the per-customer fields (object address, §1/§3.1 dates, §8.1 fee figures)
  whited out via `weg_blanking_fields()`. WHV's standard terms (§4 thresholds,
  hourly rates, insurance sum, etc.) are retained as the house standard.
- **`mv_template.pdf`** — WHV's own Immobilienverwaltervertrag (cover letter +
  contract). Per-customer fields (recipient/representative/salutation/objects,
  §1 term+dates, §6 dates, §9 year) blanked via `mv_blanking_fields()`.

## Regenerating

Both bases are produced by `stamp_pdf(source_bytes, *_blanking_fields())` over
the respective filled source PDF. The blanking field maps live in
`offer_document.py`; if a field map's coordinates change, regenerate the base
from the original source so the blanks line up with the runtime stamps.
