"""Pure-logic tests for the anfragen@ offer pipeline (ADR-0019) — the
auto-send gate + the extraction→request mapping. No DB / LLM needed.
"""

import json
from datetime import date
from decimal import Decimal

from app.config import Settings
from app.models import OfferInquiry
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


def _settings(*, enabled: bool, minimum: float = 0.8) -> Settings:
    s = Settings()
    s.offer_auto_send_enabled = enabled
    s.offer_auto_send_min_confidence = minimum
    return s


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


def test_weg_without_street_returns_none() -> None:
    assert offer_extraction.build_offer_request(_inquiry(art="WEG", street=None)) is None


def test_mv_without_recipient_returns_none() -> None:
    assert offer_extraction.build_offer_request(_inquiry(art="MV", sender=None)) is None


# --- auto_send_allowed (the kill switch + confidence gate) --------------------


def test_auto_send_blocked_when_flag_off() -> None:
    inq = _inquiry(confidence="0.99")
    assert offer_extraction.auto_send_allowed(inq, settings=_settings(enabled=False)) is False


def test_auto_send_allowed_when_flag_on_and_confident() -> None:
    inq = _inquiry(confidence="0.85")
    assert offer_extraction.auto_send_allowed(inq, settings=_settings(enabled=True)) is True


def test_auto_send_blocked_when_low_confidence() -> None:
    inq = _inquiry(confidence="0.5")
    assert offer_extraction.auto_send_allowed(inq, settings=_settings(enabled=True)) is False


def test_auto_send_blocked_when_confidence_missing() -> None:
    inq = _inquiry(confidence=None)
    assert offer_extraction.auto_send_allowed(inq, settings=_settings(enabled=True)) is False


def test_desired_start_flows_into_request() -> None:
    req = offer_extraction.build_offer_request(
        _inquiry(art="WEG", units=6, desired_start=date(2027, 3, 1))
    )
    assert req is not None
    assert req.start_date == date(2027, 3, 1)
