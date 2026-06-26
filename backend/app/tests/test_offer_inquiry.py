"""Pure-logic tests for the anfragen@ offer pipeline (ADR-0019) — the
auto-send gate + the extraction→request mapping. No DB / LLM needed.
"""

import json
from datetime import date
from decimal import Decimal

from app.models import OfferInquiry, Organization
from app.services import offer_extraction


def _inquiry(
    *,
    art: str | None = "WEG",
    units: int | None = 8,
    street: str | None = "Musterstraße 4",
    plz_city: str | None = "70000 Teststadt",
    sender: str | None = "Max Mustermann",
    confidence: str | None = "0.9",
    desired_start: date | None = None,
) -> OfferInquiry:
    i = OfferInquiry()
    i.art = art
    i.units = units
    i.sender_name = sender
    i.desired_start = desired_start
    i.confidence = Decimal(confidence) if confidence is not None else None
    extra = {}
    if street is not None:
        extra["object_street"] = street
    if plz_city is not None:
        extra["object_plz_city"] = plz_city
    i.extraction_json = json.dumps(extra)
    return i


def _org(*, enabled: bool) -> Organization:
    o = Organization()
    o.offer_auto_send_enabled = enabled
    return o


# --- build_offer_request ------------------------------------------------------


def test_build_weg_request() -> None:
    req = offer_extraction.build_offer_request(_inquiry(art="WEG", units=8))
    assert req is not None
    assert req.art == "WEG"
    assert req.units == 8
    assert req.object_street == "Musterstraße 4"
    assert req.object_plz_city == "70000 Teststadt"


def test_build_mv_request() -> None:
    req = offer_extraction.build_offer_request(_inquiry(art="MV", units=5))
    assert req is not None
    assert req.art == "MV"
    assert req.recipient_name == "Max Mustermann"
    assert req.objects


def test_unknown_art_returns_none() -> None:
    assert offer_extraction.build_offer_request(_inquiry(art=None)) is None


def test_missing_units_returns_none() -> None:
    assert offer_extraction.build_offer_request(_inquiry(units=None)) is None


def test_weg_without_street_still_builds() -> None:
    # WEG address is optional: a PLZ-only (or fully address-less) inquiry still
    # yields a sendable request so Auto-Modus can answer it.
    req = offer_extraction.build_offer_request(
        _inquiry(art="WEG", street=None, plz_city="70499 Stuttgart")
    )
    assert req is not None
    assert req.object_street == ""
    assert req.object_plz_city == "70499 Stuttgart"


def test_weg_without_any_address_still_builds() -> None:
    req = offer_extraction.build_offer_request(_inquiry(art="WEG", street=None, plz_city=None))
    assert req is not None
    assert req.object_street == ""
    assert req.object_plz_city == ""


def test_mv_without_recipient_returns_none() -> None:
    assert offer_extraction.build_offer_request(_inquiry(art="MV", sender=None)) is None


# --- auto_send_allowed (the per-org Auto-Modus gate) --------------------------


def test_auto_send_blocked_when_auto_mode_off() -> None:
    assert offer_extraction.auto_send_allowed(_inquiry(), org=_org(enabled=False)) is False


def test_auto_send_allowed_when_auto_mode_on() -> None:
    assert offer_extraction.auto_send_allowed(_inquiry(), org=_org(enabled=True)) is True


def test_auto_send_ignores_confidence() -> None:
    # "Everything that parses": even a low-confidence extraction auto-sends when
    # Auto-Modus is on (completeness is enforced by build_offer_request, not here).
    inq = _inquiry(confidence="0.1")
    assert offer_extraction.auto_send_allowed(inq, org=_org(enabled=True)) is True


def test_desired_start_flows_into_request() -> None:
    req = offer_extraction.build_offer_request(
        _inquiry(art="WEG", units=6, desired_start=date(2027, 3, 1))
    )
    assert req is not None
    assert req.start_date == date(2027, 3, 1)
