# Offer base templates (anfragen@ auto-offer, ADR-0019)

PII-free base PDFs the offer generator stamps per-customer values onto
(`app/integrations/pdf/offer_document.py`).

- **`weg_template.pdf`** — the VDIV Deutschland / Haus & Grund Deutschland
  *Verwaltervertrag für Wohnungseigentumsanlagen*, **Februar 2025** Mustervertrag
  (15 pages), used by WHV as a VDIV member/licensee. Source: WHV's pre-filled
  blank form (house-standard terms typed in — §4 thresholds, §7.2 insurance,
  §8.2 hourly rates, §8.3.2 Kreis, checkboxes — per-customer slots left empty).
  The source was an AcroForm whose typed values lived in Widget/FreeText
  ANNOTATIONS (rendered above any overlay, and dropped by some viewers), so the
  committed base is the **flattened** version:

  ```sh
  gs -q -o weg_template.pdf -sDEVICE=pdfwrite -dPDFSETTINGS=/prepress \
     -dPreserveAnnots=false <filled-source>.pdf
  ```

  The runtime stamps (object address, §1/§3.1 dates, §8.1 fee figures) sit
  directly on the form's empty ruled lines — no blanking pass needed.
  **Pages 16–17** are the appended VDIV-NRW "Nachweis der Verwalterbestellung"
  (DKB bank form): info page verbatim + the form page blanked from a filled
  source ("Wagner Hausverwaltung GmbH" as die Firma is kept). The offer
  overlay never stamps these pages — the WEG fills them after signing.
- **`mv_template.pdf`** — WHV's own Immobilienverwaltervertrag (cover letter +
  contract). Per-customer fields (recipient/representative/salutation/objects,
  §1 term+dates, §6 dates, §9 year) blanked via `mv_blanking_fields()` from a
  real filled offer. **Page 9** is the appended DKB "Verifizierung der
  Angaben von wirtschaftlich Berechtigten zu Treuhandkonten", blanked from a
  filled source (Kontoinhaber block kept).

**Blanked form pages are RASTERIZED** (200 dpi via pdftoppm, re-embedded as
an image page): a whiteout cover only hides text visually — the PII would
remain extractable from the text layer of an emailed offer. Rasterizing
removes it for real; verify with `pdftotext -f <page> -l <page>` returning
nothing.

## Updating the WEG base

When VDIV/Haus & Grund publish a new Mustervertrag: fill WHV's standard terms,
flatten it with the `gs` command above, replace `weg_template.pdf`, then
re-measure the per-customer field coordinates (`pdftotext -bbox`, top-left
points) and update `_weg_fields()` in `offer_document.py`. Verify by rendering
a probe offer and eyeballing pages 1, 2 and the §8.1 page.
