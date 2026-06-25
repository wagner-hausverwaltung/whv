"""Unit tests for the offer (Angebot) pricing engine.

Anchored to the real template values: the WEG examples print a flat 270 € net
/ 321,30 € gross monthly with a +6 €/month/year escalator (6 units x 45 €,
hitting the 270 € floor; escalator = 6 x 1 €); the MV Müller template prints
30 €/unit/month net escalating +1 €/unit/year, 2-year term 01.06.2026 ->
31.05.2028.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services import offer_pricing as op

# --- WEG ----------------------------------------------------------------------


def test_weg_six_units_matches_example_flat_270() -> None:
    p = op.price_weg(units=6, start_date=date(2027, 1, 1), term_years=4)
    assert p.rate_per_unit_net == Decimal("45")
    assert p.floor_applied is False  # 6 x 45 = 270, exactly the floor
    assert p.year1_monthly_net == Decimal("270.00")
    assert p.year1_monthly_gross == Decimal("321.30")
    assert p.monthly_escalator_net == Decimal("6.00")  # 6 units x 1 €


def test_weg_small_weg_hits_floor() -> None:
    p = op.price_weg(units=4, start_date=date(2027, 1, 1))
    assert p.floor_applied is True  # 4 x 45 = 180 < 270
    assert p.year1_monthly_net == Decimal("270.00")
    assert p.monthly_escalator_net == Decimal("4.00")  # escalator stays per-unit


def test_weg_large_weg_uses_discounted_rate() -> None:
    p = op.price_weg(units=20)
    assert p.rate_per_unit_net == Decimal("35")  # > 15 units
    assert p.year1_monthly_net == Decimal("700.00")  # 20 x 35
    assert p.monthly_escalator_net == Decimal("20.00")


def test_weg_explicit_rate_override() -> None:
    p = op.price_weg(units=10, rate_per_unit_net=Decimal("50"))
    assert p.year1_monthly_net == Decimal("500.00")
    assert p.floor_applied is False


def test_weg_escalation_schedule() -> None:
    p = op.price_weg(units=6, start_date=date(2027, 1, 1), term_years=4)
    nets = [y.monthly_net for y in p.schedule]
    assert nets == [Decimal("270.00"), Decimal("276.00"), Decimal("282.00"), Decimal("288.00")]
    # gross tracks net x 1.19
    assert p.schedule[1].monthly_gross == Decimal("328.44")
    assert p.schedule[0].annual_net == Decimal("3240.00")  # 270 x 12


# --- MV -----------------------------------------------------------------------


def test_mv_per_unit_matches_template() -> None:
    p = op.price_mv(units=10, start_date=date(2026, 6, 1), term_years=2)
    assert p.rate_per_unit_net == Decimal("30")
    assert p.year1_monthly_net == Decimal("300.00")  # 10 x 30 (whole-object total)
    assert p.per_unit_escalator_net == Decimal("1")
    assert p.monthly_escalator_net == Decimal("10.00")  # 10 units x 1 €


def test_mv_dates_match_template() -> None:
    p = op.price_mv(units=5, start_date=date(2026, 6, 1), term_years=2)
    assert p.end_date == date(2028, 5, 31)
    assert p.first_escalation_date == date(2027, 6, 1)


def test_mv_escalation_schedule() -> None:
    p = op.price_mv(units=8, start_date=date(2027, 1, 1), term_years=4)
    # per-unit: 30, 31, 32, 33 -> totals x 8
    assert [y.monthly_net for y in p.schedule] == [
        Decimal("240.00"),
        Decimal("248.00"),
        Decimal("256.00"),
        Decimal("264.00"),
    ]


# --- shared helpers -----------------------------------------------------------


def test_default_start_is_jan_next_year() -> None:
    assert op.default_start_date(today=date(2026, 6, 25)) == date(2027, 1, 1)


def test_contract_end_four_year_default() -> None:
    p = op.price_weg(units=6, start_date=date(2027, 1, 1))
    assert p.term_years == 4
    assert p.end_date == date(2030, 12, 31)
    assert p.first_escalation_date == date(2028, 1, 1)


def test_default_start_when_none_uses_next_year() -> None:
    p = op.price_weg(units=6, today=date(2026, 6, 25))
    assert p.start_date == date(2027, 1, 1)
    assert p.end_date == date(2030, 12, 31)


def test_price_offer_dispatch() -> None:
    assert op.price_offer("weg", units=6).art == "WEG"
    assert op.price_offer(" MV ", units=6).art == "MV"
    with pytest.raises(ValueError):
        op.price_offer("gewerbe", units=6)


def test_invalid_units_raise() -> None:
    with pytest.raises(ValueError):
        op.price_weg(units=0)
    with pytest.raises(ValueError):
        op.price_mv(units=-1)
