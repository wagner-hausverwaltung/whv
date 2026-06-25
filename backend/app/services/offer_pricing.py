"""Offer (Angebot) pricing engine for the anfragen@ auto-offer feature.

Pure, side-effect-free fee maths for the two product lines WHV quotes:

* **WEG** (Wohnungseigentumsverwaltung) — the official VDIV/Haus & Grund
  Verwaltervertrag. The contract prints a *flat* monthly Festvergütung for the
  whole WEG (§ 8.1 a) plus a *flat* yearly escalator (§ 8.1 b), even though we
  price it per unit behind the scenes:

    year-1 monthly base (net) = max(units x rate, 270 €)        # 270 = floor
    rate (net/unit/month)     = 45 €, or 35 € when units > 15   # defaults
    yearly escalator (net)    = units x 1 €/month               # whole-WEG sum

  So a 6-unit WEG at 45 €/unit = 270 € (hits the floor) with a +6 €/month/year
  escalator — exactly what the Hermann-Essig / Königsseestraße examples print.

* **MV** (Mietverwaltung) — WHV's own Immobilienverwaltervertrag. The contract
  prints a *per-unit* monthly fee (§ 6) that escalates per unit each year:

    monthly fee (net)      = 30 €/unit/month                    # year 1
    escalator (net)        = +1 €/unit/year, from start + 1 year

All figures are quoted net; gross adds the statutory VAT (19 %). The German
number/label formatting lives in the PDF-stamping layer, not here — this module
only produces :class:`Decimal` amounts and the year-by-year schedule that the
generator stamps into the template.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# --- standing rules (overridable per call) -----------------------------------

VAT_RATE = Decimal("0.19")
"""Statutory German Umsatzsteuer applied to the net Verwaltervergütung."""

WEG_FLOOR_NET = Decimal("270")
"""§ 8.1: minimum monthly Festvergütung for a WEG, regardless of unit count."""

WEG_RATE_STANDARD = Decimal("45")
"""Default WEG net rate per unit/month (the 40-50 € band, mid-point)."""

WEG_RATE_LARGE = Decimal("35")
"""Discounted WEG net rate per unit/month once the WEG exceeds the threshold."""

WEG_LARGE_THRESHOLD = 15
"""Above this many units the discounted large-WEG rate may apply."""

WEG_ESCALATOR_PER_UNIT_NET = Decimal("1")
"""§ 8.1 b: yearly increase, 1 €/unit/month — summed over the WEG per year."""

MV_RATE_STANDARD = Decimal("30")
"""§ 6: default MV net rate per Wohneinheit/month (year 1)."""

MV_ESCALATOR_PER_UNIT_NET = Decimal("1")
"""§ 6: yearly increase, 1 €/unit/month, first applied at start + 1 year."""

DEFAULT_TERM_YEARS = 4
"""Default contract Laufzeit when the inquiry doesn't state one."""

_CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    """Round a money amount to whole cents, half-up (German convention)."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


# --- date helpers -------------------------------------------------------------


def default_start_date(*, today: date | None = None) -> date:
    """When the inquiry gives no start date, assume 1 January of next year."""
    ref = today or date.today()
    return date(ref.year + 1, 1, 1)


def _add_years(d: date, years: int) -> date:
    """Add whole years, clamping 29 Feb -> 28 Feb on non-leap targets."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb -> non-leap year
        return d.replace(year=d.year + years, day=28)


def contract_end_date(start: date, term_years: int) -> date:
    """End = the day before the term-anniversary of the start.

    e.g. start 01.01.2027, 4 years -> 31.12.2030 (mirrors the MV template's
    01.06.2026 -> 31.05.2028 over a 2-year term).
    """
    from datetime import timedelta

    return _add_years(start, term_years) - timedelta(days=1)


# --- result types -------------------------------------------------------------


@dataclass(frozen=True)
class YearFee:
    """Fee for one contract year (1-based)."""

    year: int
    monthly_net: Decimal
    monthly_gross: Decimal
    annual_net: Decimal
    annual_gross: Decimal


@dataclass(frozen=True)
class OfferPricing:
    """Computed pricing for one offer, ready for the PDF-stamping layer."""

    art: str  # "WEG" | "MV"
    units: int
    rate_per_unit_net: Decimal  # the year-1 per-unit rate used
    floor_applied: bool  # WEG only — True when the 270 € floor lifted the base
    vat_rate: Decimal
    start_date: date
    end_date: date
    term_years: int
    first_escalation_date: date
    # Headline year-1 monthly figures (what § 8.1 a / § 6 print).
    year1_monthly_net: Decimal
    year1_monthly_gross: Decimal
    # WEG: absolute whole-WEG monthly escalator (units x 1). MV: per-unit (1).
    monthly_escalator_net: Decimal
    per_unit_escalator_net: Decimal
    schedule: list[YearFee]


def _build_schedule(
    *, year1_monthly_net: Decimal, monthly_escalator_net: Decimal, term_years: int, vat: Decimal
) -> list[YearFee]:
    out: list[YearFee] = []
    multiplier = Decimal(1) + vat
    for y in range(1, term_years + 1):
        m_net = _money(year1_monthly_net + monthly_escalator_net * (y - 1))
        m_gross = _money(m_net * multiplier)
        a_net = _money(m_net * 12)
        a_gross = _money(m_gross * 12)
        out.append(
            YearFee(
                year=y,
                monthly_net=m_net,
                monthly_gross=m_gross,
                annual_net=a_net,
                annual_gross=a_gross,
            )
        )
    return out


def price_weg(
    *,
    units: int,
    start_date: date | None = None,
    term_years: int = DEFAULT_TERM_YEARS,
    rate_per_unit_net: Decimal | None = None,
    vat_rate: Decimal = VAT_RATE,
    today: date | None = None,
) -> OfferPricing:
    """Price a WEG offer.

    The base is the per-unit rate x units, floored at 270 €; the yearly
    escalator is 1 €/unit/month summed across the WEG (§ 8.1 a/b).
    """
    if units < 1:
        raise ValueError("units must be >= 1")
    if term_years < 1:
        raise ValueError("term_years must be >= 1")

    rate = rate_per_unit_net
    if rate is None:
        rate = WEG_RATE_LARGE if units > WEG_LARGE_THRESHOLD else WEG_RATE_STANDARD

    raw_base = rate * units
    year1_net = _money(max(raw_base, WEG_FLOOR_NET))
    floor_applied = raw_base < WEG_FLOOR_NET
    monthly_escalator = _money(WEG_ESCALATOR_PER_UNIT_NET * units)

    start = start_date or default_start_date(today=today)
    schedule = _build_schedule(
        year1_monthly_net=year1_net,
        monthly_escalator_net=monthly_escalator,
        term_years=term_years,
        vat=vat_rate,
    )
    return OfferPricing(
        art="WEG",
        units=units,
        rate_per_unit_net=rate,
        floor_applied=floor_applied,
        vat_rate=vat_rate,
        start_date=start,
        end_date=contract_end_date(start, term_years),
        term_years=term_years,
        first_escalation_date=_add_years(start, 1),
        year1_monthly_net=schedule[0].monthly_net,
        year1_monthly_gross=schedule[0].monthly_gross,
        monthly_escalator_net=monthly_escalator,
        per_unit_escalator_net=WEG_ESCALATOR_PER_UNIT_NET,
        schedule=schedule,
    )


def price_mv(
    *,
    units: int,
    start_date: date | None = None,
    term_years: int = DEFAULT_TERM_YEARS,
    rate_per_unit_net: Decimal = MV_RATE_STANDARD,
    vat_rate: Decimal = VAT_RATE,
    today: date | None = None,
) -> OfferPricing:
    """Price an MV offer.

    Per-unit, per-month (§ 6): 30 €/unit/month year 1, escalating +1 €/unit
    each year from start + 1 year. The headline monthly figure is the whole-
    object total (units x per-unit rate); the per-unit rate is what § 6 prints.
    """
    if units < 1:
        raise ValueError("units must be >= 1")
    if term_years < 1:
        raise ValueError("term_years must be >= 1")

    year1_net = _money(rate_per_unit_net * units)
    monthly_escalator = _money(MV_ESCALATOR_PER_UNIT_NET * units)

    start = start_date or default_start_date(today=today)
    schedule = _build_schedule(
        year1_monthly_net=year1_net,
        monthly_escalator_net=monthly_escalator,
        term_years=term_years,
        vat=vat_rate,
    )
    return OfferPricing(
        art="MV",
        units=units,
        rate_per_unit_net=rate_per_unit_net,
        floor_applied=False,
        vat_rate=vat_rate,
        start_date=start,
        end_date=contract_end_date(start, term_years),
        term_years=term_years,
        first_escalation_date=_add_years(start, 1),
        year1_monthly_net=schedule[0].monthly_net,
        year1_monthly_gross=schedule[0].monthly_gross,
        monthly_escalator_net=monthly_escalator,
        per_unit_escalator_net=MV_ESCALATOR_PER_UNIT_NET,
        schedule=schedule,
    )


def price_offer(
    art: str,
    *,
    units: int,
    start_date: date | None = None,
    term_years: int = DEFAULT_TERM_YEARS,
    rate_per_unit_net: Decimal | None = None,
    vat_rate: Decimal = VAT_RATE,
    today: date | None = None,
) -> OfferPricing:
    """Dispatch to :func:`price_weg` / :func:`price_mv` by product line."""
    key = art.strip().upper()
    if key == "WEG":
        return price_weg(
            units=units,
            start_date=start_date,
            term_years=term_years,
            rate_per_unit_net=rate_per_unit_net,
            vat_rate=vat_rate,
            today=today,
        )
    if key == "MV":
        return price_mv(
            units=units,
            start_date=start_date,
            term_years=term_years,
            rate_per_unit_net=rate_per_unit_net or MV_RATE_STANDARD,
            vat_rate=vat_rate,
            today=today,
        )
    raise ValueError(f"unknown offer art {art!r} (expected WEG or MV)")
