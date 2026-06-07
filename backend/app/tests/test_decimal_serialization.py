"""Money / area Decimal fields must serialise to JSON **numbers**, not strings.

Pydantic v2 defaults ``Decimal`` to a JSON *string*, which the iOS Swift
Codable clients (typed ``Double``) cannot decode — a quoted number makes the
decode throw and silently empties whole sections (Dienstleister, Mein
Hausgeldkonto, invoice detail, Mieter settlement, unit MEA/area). ``types.py``
fixes that with ``DecimalAsFloat``; these tests guard the contract so a future
schema edit can't regress it. (``document.py`` deliberately stays a string —
the shipped iOS build decodes that one field as ``String?``.)
"""

import uuid
from decimal import Decimal

from app.models.contact import ContactKind
from app.schemas.account import HausgeldAccountResponse, PostingItemResponse
from app.schemas.invoice import InvoiceLineItemResponse
from app.schemas.rent_settlement import RentSettlementResponse
from app.schemas.unit import UnitResponse
from app.schemas.vendor import VendorInvoiceSummary, VendorSummary


def test_vendor_amounts_serialise_as_numbers() -> None:
    vendor = VendorSummary(
        contact_id=uuid.uuid4(),
        name="EnBW AG",
        kind=ContactKind.COMPANY,
        invoice_count=11,
        total_amount=Decimal("-24449.98"),
        recent_invoices=[
            VendorInvoiceSummary(id=uuid.uuid4(), name="3836", amount=Decimal("-24449.98")),
        ],
    )
    data = vendor.model_dump(mode="json")
    assert data["total_amount"] == -24449.98
    assert isinstance(data["total_amount"], float)
    assert isinstance(data["recent_invoices"][0]["amount"], float)
    # No quoted number anywhere on the wire — what actually broke iOS.
    assert '"-24449.98"' not in vendor.model_dump_json()


def test_account_balance_and_bookings_serialise_as_numbers() -> None:
    acc = HausgeldAccountResponse(
        account_id=10,
        account_hr_id="2000/4/1",
        name="Hausgeld 4 - Luis Wagner",
        balance=Decimal("-250.00"),
        bookings=[
            PostingItemResponse(
                post_date="2026-01-15", booking_text="Hausgeld Januar", amount=Decimal("-250.00")
            )
        ],
    )
    data = acc.model_dump(mode="json")
    assert isinstance(data["balance"], float) and data["balance"] == -250.0
    assert isinstance(data["bookings"][0]["amount"], float)


def test_invoice_unit_settlement_decimals_serialise_as_numbers() -> None:
    line = InvoiceLineItemResponse(
        account_name="Primärenergie", amount=Decimal("250.00"), vat_percentage=Decimal("19")
    )
    ld = line.model_dump(mode="json")
    assert isinstance(ld["amount"], float)
    assert isinstance(ld["vat_percentage"], float)

    unit = UnitResponse(id=uuid.uuid4(), type="APARTMENT", voting_share=Decimal("123.45"))
    assert isinstance(unit.model_dump(mode="json")["voting_share"], float)

    rs = RentSettlementResponse(
        period_from="2025-01-01",
        period_until="2025-12-31",
        due_date="2026-02-01",
        rent_income=Decimal("12000.00"),
        payout=Decimal("9500.50"),
        balance=Decimal("2499.50"),
        state="FINAL",
    )
    rd = rs.model_dump(mode="json")
    assert isinstance(rd["rent_income"], float)
    assert isinstance(rd["balance"], float)


def test_none_decimals_stay_null() -> None:
    # The `| None` branch must still serialise to null (serializer not invoked).
    acc = HausgeldAccountResponse(
        account_id=None, account_hr_id=None, name=None, balance=None, bookings=[]
    )
    assert acc.model_dump(mode="json")["balance"] is None
