"""Offer (Angebot) PDF generator — fills the WEG / MV templates per customer.

Built on :mod:`offer_overlay`: each product line has a coordinate map of the
per-customer fields measured from the real template (``pdftotext -bbox``), and
a ``render_*_offer`` function that white-outs those fields and re-stamps the
inquiry's values + the computed pricing (see :mod:`app.services.offer_pricing`).

Field maps are intentionally data, not code — adjusting a position is a number
change here, not a logic change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth

from app.integrations.pdf.offer_overlay import StampField, stamp_pdf
from app.services.offer_pricing import OfferPricing

_TEMPLATE_DIR = Path(__file__).parent / "assets" / "offer_templates"


def load_base_template(art: str) -> bytes:
    """Read the committed blanked base PDF for a product line ("WEG"|"MV")."""
    key = art.strip().upper()
    name = {"WEG": "weg_template.pdf", "MV": "mv_template.pdf"}.get(key)
    if name is None:
        raise ValueError(f"unknown offer art {art!r}")
    return (_TEMPLATE_DIR / name).read_bytes()


# --- German formatting helpers ------------------------------------------------


def de_money(value: Decimal) -> str:
    """Format a Decimal as German money without the symbol: 1234.5 -> 1.234,50."""
    sign = "-" if value < 0 else ""
    whole, frac = f"{abs(value):.2f}".split(".")
    groups: list[str] = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return f"{sign}{'.'.join(groups)},{frac}"


def de_date(d: date) -> str:
    """DD.MM.YYYY."""
    return d.strftime("%d.%m.%Y")


def de_month_year(d: date) -> str:
    """MM.YY (the § 3.1 Bestellungszeitraum format)."""
    return d.strftime("%m.%y")


# --- WEG ----------------------------------------------------------------------


@dataclass(frozen=True)
class WegOfferInput:
    """Per-customer inputs for a WEG Verwaltervertrag offer."""

    object_street: str  # "Musterstraße 12"
    object_plz_city: str  # "70123 Stuttgart"
    pricing: OfferPricing
    # A fresh offer has no resolution yet, so the § 1 Beschluss date is blank.
    beschluss_date: date | None = None


# Coordinate map for the WEG VDIV/Haus & Grund Verwaltervertrag, measured from
# the Februar-2025 Mustervertrag base (pdftotext -bbox, top-left points). The
# committed base is WHV's pre-filled blank form (house-standard terms typed in,
# per-customer slots empty), so the stamps sit directly on the form's ruled
# lines — no cover rectangles needed except where we replace form wording.
def _weg_fields(inp: WegOfferInput) -> list[StampField]:
    p = inp.pricing
    fields: list[StampField] = [
        # Page 1 — parties block: WEG object address on the two blank rules
        # under "Zwischen der Wohnungseigentümergemeinschaft".
        StampField(page=1, text=inp.object_street, x=60.0, y_top=612.3, size=9.0),
        StampField(page=1, text=inp.object_plz_city, x=60.0, y_top=632.8, size=9.0),
        # Page 2 — § 1 Bestellung: Beschluss date (blank for an offer) + the
        # "für die Zeit vom ___ bis ___" period.
        StampField(
            page=2,
            text=de_date(inp.beschluss_date) if inp.beschluss_date else "",
            x=149.0,
            y_top=152.0,
            size=8.5,
        ),
        StampField(page=2, text=de_date(p.start_date), x=397.5, y_top=152.0, size=8.5),
        StampField(page=2, text=de_date(p.end_date), x=478.5, y_top=152.0, size=8.5),
        # Page 2 — § 3.1 Bestellungszeitraum (MM.YY — the blanks are short).
        StampField(page=2, text=de_month_year(p.start_date), x=423.5, y_top=315.7, size=8.5),
        StampField(page=2, text=de_month_year(p.end_date), x=460.3, y_top=315.7, size=8.5),
        # Page 10 — § 8.1 a) Festvergütung net / gross into the form's blanks.
        StampField(page=10, text=de_money(p.year1_monthly_net), x=213.0, y_top=343.1, size=8.0),
        StampField(page=10, text=de_money(p.year1_monthly_gross), x=416.0, y_top=343.1, size=8.0),
        # Page 10 — § 8.1 b) annual escalator, expressed for the whole WEG.
        # The form's own "______Euro." + typed-in "pro Monat" are covered and
        # re-written so the net/MwSt + whole-WEG qualifiers stay explicit.
        StampField(
            page=10,
            text=f"{de_money(p.monthly_escalator_net)} EUR + MwSt pro Monat für die WEG",
            x=214.0,
            y_top=382.5,
            size=7.5,
            cover=(212.0, 380.0, 371.0, 392.5),
        ),
    ]
    return fields


def render_weg_offer(base_pdf: bytes, inp: WegOfferInput) -> bytes:
    """Stamp a per-customer WEG offer onto the blanked WEG template."""
    return stamp_pdf(base_pdf, _weg_fields(inp))


# The WEG base (Februar-2025 Mustervertrag) is committed as WHV's pre-filled
# blank form — its per-customer slots are already empty, so unlike the MV base
# below it needs no one-off blanking pass.
from app.services.offer_pricing import price_mv as _price_mv  # noqa: E402

# --- MV (Mietverwaltung) ------------------------------------------------------


def _wrap(text: str, max_width: float, size: float, font: str = "Helvetica") -> list[str]:
    """Greedy word-wrap to ``max_width`` points at the given font size."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if stringWidth(trial, font, size) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


@dataclass(frozen=True)
class MvOfferInput:
    """Per-customer inputs for a Mietverwaltung offer (cover + contract)."""

    recipient_name: str  # Auftraggeber, e.g. "Heinz-Dieter Müller"
    recipient_street: str
    recipient_plz_city: str
    salutation: str  # e.g. "Sehr geehrter Herr Müller,"
    objects: list[str]  # ["Wildensteinstraße 60, 70469 Stuttgart", ...]
    pricing: OfferPricing
    offer_date: date
    # Optional legal representative (vertreten durch …).
    representative_name: str | None = None
    representative_street: str | None = None
    representative_plz_city: str | None = None


# MV cover (page 1) is a letter; recipient / representative / salutation /
# object lines are block-replaced (variable width, own lines), the offer date +
# all contract dates are token-replaced (Helvetica digits are tabular, so a
# DD.MM.YYYY swap keeps the exact width and never reflows surrounding prose).
# Boxes measured from the Müller template (pdftotext -bbox, top-left points).
def _mv_fields(inp: MvOfferInput) -> list[StampField]:
    p = inp.pricing
    objects_sentence = "die Mietverwaltung der Objekte " + " und ".join(inp.objects) + "."
    fields: list[StampField] = [
        # --- Page 1 cover: recipient block ---
        StampField(
            page=1,
            text=inp.recipient_name,
            x=73.0,
            y_top=123.0,
            size=11.0,
            cover=(72.0, 121.0, 320.0, 138.0),
        ),
        StampField(
            page=1,
            text=inp.recipient_street,
            x=73.0,
            y_top=139.5,
            size=11.0,
            cover=(72.0, 138.0, 320.0, 155.0),
        ),
        StampField(
            page=1,
            text=inp.recipient_plz_city,
            x=73.0,
            y_top=156.0,
            size=11.0,
            cover=(72.0, 155.0, 320.0, 171.0),
        ),
        # Offer date (top-right, right-aligned).
        StampField(
            page=1,
            text=de_date(inp.offer_date),
            x=565.0,
            y_top=150.5,
            size=10.5,
            cover=(498.0, 149.0, 567.0, 165.0),
            align="right",
        ),
        # Salutation.
        StampField(
            page=1,
            text=inp.salutation,
            x=73.0,
            y_top=319.0,
            size=11.0,
            cover=(72.0, 317.0, 360.0, 334.0),
        ),
    ]
    # Representative block (optional).
    if inp.representative_name:
        fields += [
            StampField(
                page=1,
                text=inp.representative_name,
                x=73.0,
                y_top=222.0,
                size=11.0,
                cover=(72.0, 220.0, 320.0, 238.0),
            ),
            StampField(
                page=1,
                text=inp.representative_street or "",
                x=73.0,
                y_top=238.5,
                size=11.0,
                cover=(72.0, 237.0, 320.0, 254.0),
            ),
            StampField(
                page=1,
                text=inp.representative_plz_city or "",
                x=73.0,
                y_top=255.0,
                size=11.0,
                cover=(72.0, 254.0, 320.0, 271.0),
            ),
        ]
    else:  # erase the "vertreten durch" label + the representative block
        fields.append(
            StampField(
                page=1, text="", x=73.0, y_top=222.0, size=11.0, cover=(72.0, 187.0, 320.0, 271.0)
            )
        )
    # Intro object sentence — re-rendered (wrapped) over its two template lines.
    wrapped = _wrap(objects_sentence, max_width=467.0, size=10.5)
    fields.append(
        StampField(
            page=1, text="", x=73.0, y_top=401.0, size=10.5, cover=(72.0, 399.0, 545.0, 434.0)
        )
    )
    for i, line in enumerate(wrapped[:2]):
        fields.append(StampField(page=1, text=line, x=73.0, y_top=401.0 + i * 16.5, size=10.5))
    # --- Page 3 § 1 Vertragsdauer: term count + start / end (token swap) ---
    fields += [
        # "... auf die Dauer von N Jahren fest ..." — keep prose, swap the digit.
        StampField(
            page=3,
            text=str(p.term_years),
            x=283.3,
            y_top=142.1,
            size=10.5,
            cover=(282.0, 141.0, 291.5, 157.0),
        ),
        StampField(
            page=3,
            text=de_date(p.start_date),
            x=102.2,
            y_top=159.0,
            size=10.5,
            cover=(101.0, 158.0, 165.0, 173.0),
        ),
        StampField(
            page=3,
            text=f"{de_date(p.end_date)}.",
            x=256.4,
            y_top=159.0,
            size=10.5,
            cover=(255.0, 158.0, 324.0, 173.0),
        ),
    ]
    # --- Page 7 § 6 Vergütung: first escalation + first due (token swap) ---
    fields += [
        StampField(
            page=7,
            text=f"{de_date(p.first_escalation_date)}.",
            x=174.7,
            y_top=177.5,
            size=10.5,
            cover=(173.0, 176.0, 240.0, 192.0),
        ),
        StampField(
            page=7,
            text=f"{de_date(p.start_date)}.",
            x=426.5,
            y_top=227.0,
            size=10.5,
            cover=(425.0, 226.0, 492.0, 242.0),
        ),
    ]
    # --- Page 8 § 9: Betriebskostenabrechnung year (token swap) ---
    fields.append(
        StampField(
            page=8,
            text=str(p.start_date.year),
            x=437.5,
            y_top=225.5,
            size=10.5,
            cover=(436.0, 224.0, 467.0, 240.0),
        )
    )
    # --- Page 2 contract body: Auftraggeber parties block (centered lines) ---
    cx = 314.0  # the parties/objects lines are centered around here, not page mid
    fields += [
        StampField(
            page=2,
            text=inp.recipient_name,
            x=cx,
            y_top=337.0,
            size=11.0,
            cover=(150.0, 335.0, 480.0, 353.0),
            align="center",
        ),
        StampField(
            page=2,
            text=inp.recipient_street,
            x=cx,
            y_top=354.0,
            size=11.0,
            cover=(150.0, 353.0, 480.0, 369.0),
            align="center",
        ),
        StampField(
            page=2,
            text=inp.recipient_plz_city,
            x=cx,
            y_top=370.0,
            size=11.0,
            cover=(150.0, 369.0, 480.0, 386.0),
            align="center",
        ),
    ]
    if inp.representative_name:
        fields += [
            StampField(
                page=2,
                text=inp.representative_name,
                x=cx,
                y_top=436.0,
                size=11.0,
                cover=(150.0, 434.0, 480.0, 452.0),
                align="center",
            ),
            StampField(
                page=2,
                text=inp.representative_street or "",
                x=cx,
                y_top=453.0,
                size=11.0,
                cover=(150.0, 452.0, 480.0, 468.0),
                align="center",
            ),
            StampField(
                page=2,
                text=inp.representative_plz_city or "",
                x=cx,
                y_top=469.0,
                size=11.0,
                cover=(150.0, 468.0, 480.0, 485.0),
                align="center",
            ),
        ]
    else:  # erase "vertreten durch" + the representative lines
        fields.append(
            StampField(
                page=2, text="", x=cx, y_top=436.0, size=11.0, cover=(150.0, 401.0, 480.0, 485.0)
            )
        )
    # Vertragsgegenstand — the managed objects, one centered line each.
    fields.append(
        StampField(
            page=2, text="", x=cx, y_top=651.0, size=11.0, cover=(150.0, 649.0, 480.0, 705.0)
        )
    )
    for i, obj in enumerate(inp.objects[:3]):
        fields.append(
            StampField(page=2, text=obj, x=cx, y_top=651.0 + i * 16.5, size=11.0, align="center")
        )
    return fields


def render_mv_offer(base_pdf: bytes, inp: MvOfferInput) -> bytes:
    """Stamp a per-customer MV offer onto the blanked MV template."""
    return stamp_pdf(base_pdf, _mv_fields(inp))


def mv_blanking_fields() -> list[StampField]:
    """Cover-only fields that turn the filled MV source into a PII-free base."""
    dummy = MvOfferInput(
        recipient_name="",
        recipient_street="",
        recipient_plz_city="",
        salutation="",
        objects=[""],
        pricing=_DUMMY_MV,
        offer_date=date(2027, 1, 1),
        representative_name="x",
        representative_street="",
        representative_plz_city="",
    )
    return [
        StampField(page=f.page, text="", x=f.x, y_top=f.y_top, size=f.size, cover=f.cover)
        for f in _mv_fields(dummy)
        if f.cover is not None
    ]


_DUMMY_MV = _price_mv(units=10, start_date=date(2027, 1, 1))
