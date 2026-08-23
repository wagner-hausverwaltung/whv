"""Auslagen-Rechnung Fahrtkosten je Objekt (ADR-0020, Phase 5).

Default billing rule per property type, sequential numbering, the immutable
line snapshot, and the reportlab invoice. Contract background: see
models/trip_invoice.py — the rule only PRE-SELECTS; the Verwalter decides.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.pdf import company
from app.integrations.pdf.assembly_document import _LOGO_PATH
from app.models import Property, PropertyType, Trip, TripInvoice, TripPurpose, TripStatus
from app.services.trip_statement import _PURPOSE_LABEL, de_km, de_money

_BERLIN = ZoneInfo("Europe/Berlin")
_FONT = "Helvetica"
_BOLD = "Helvetica-Bold"
NUMBER_PREFIX = "WHV-FK"


class TripInvoiceError(ValueError):
    """Validation error → HTTP 400/409 at the endpoint (see `status`)."""

    def __init__(self, detail: str, status: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


@dataclass(frozen=True)
class BillingRule:
    rate_cents_per_km: int
    # Purposes the UI pre-selects; empty = nothing pre-selected.
    suggested_purposes: frozenset[str]
    legal_basis: str
    hint: str


_WEG_RULE = BillingRule(
    rate_cents_per_km=42,
    suggested_purposes=frozenset({TripPurpose.ETV.value}),
    legal_basis=(
        "Fahrtkosten für die Teilnahme an Beirats-/Eigentümerversammlungen außerhalb "
        "Kreis Stuttgart gemäß § 8.3.2 WEG-Verwaltervertrag — steuerrechtlicher "
        "Kostensatz (derzeit 0,42 € je km)."
    ),
    hint=(
        "WEG: Laut Verwaltervertrag sind nur Fahrten zu Beirats-/Eigentümerversammlungen "
        "außerhalb Kreis Stuttgart erstattungsfähig (0,42 €/km). ETV-Fahrten sind vorgehakt "
        "— bitte prüfen, ob die Versammlung außerhalb stattfand."
    ),
)
_MV_RULE = BillingRule(
    rate_cents_per_km=50,
    suggested_purposes=frozenset(),
    legal_basis=(
        "Fahrtkosten gemäß Ziffer 5.4 Verwaltervertrag (VDIV 2026): 0,50 € je gefahrenem "
        "Kilometer. Fahrten zwischen dem Sitz der Verwaltung und dem Objekt sind mit der "
        "Auslagenpauschale nach Ziffer 5.3 abgegolten."
    ),
    hint=(
        "MV/SEV: Fahrten Verwaltung ↔ Objekt sind in der Auslagenpauschale (Ziffer 5.3) "
        "enthalten; nur darüber hinausgehende Fahrten (0,50 €/km) anhaken. Nichts vorgehakt."
    ),
)


def default_rule(property_type: PropertyType) -> BillingRule:
    """Impower's enum: OWNER = WEG, RENTAL = MV, STRATA = SEV (see
    web/src/lib/propertyType.ts). SEV runs on the VDIV MV/SEV contract."""
    return _WEG_RULE if property_type == PropertyType.OWNER else _MV_RULE


def billable_filter(stmt: Any, *, org_id: uuid.UUID, property_id: uuid.UUID, until: date) -> Any:
    """Confirmed, not yet billed, non-private trips of the property up to
    `until` (Berlin day, inclusive)."""
    end = datetime.combine(until, datetime.max.time(), tzinfo=_BERLIN)
    return stmt.where(
        Trip.organization_id == org_id,
        Trip.property_id == property_id,
        Trip.status == TripStatus.CONFIRMED.value,
        Trip.invoice_id.is_(None),
        Trip.purpose != TripPurpose.PRIVAT.value,
        Trip.distance_m > 0,
        Trip.started_at <= end,
    )


def line_amount_cents(distance_m: int, rate_cents_per_km: int) -> int:
    return int(
        (Decimal(distance_m) / 1000 * rate_cents_per_km).quantize(Decimal("1"), ROUND_HALF_UP)
    )


def vat_cents(net_cents: int, vat_percent: Decimal) -> int:
    return int((Decimal(net_cents) * vat_percent / 100).quantize(Decimal("1"), ROUND_HALF_UP))


async def next_number(session: AsyncSession, org_id: uuid.UUID, year: int) -> str:
    """WHV-FK-<year>-<0001>, sequential per org and year. The unique
    constraint on (org, number) is the safety net for a concurrent create."""
    prefix = f"{NUMBER_PREFIX}-{year}-"
    count = await session.scalar(
        select(func.count())
        .select_from(TripInvoice)
        .where(TripInvoice.organization_id == org_id, TripInvoice.number.like(f"{prefix}%"))
    )
    return f"{prefix}{(count or 0) + 1:04d}"


def property_address(p: Property) -> str | None:
    street = " ".join(part for part in (p.street, p.number) if part).strip()
    zip_city = " ".join(part for part in (p.postal_code, p.city) if part).strip()
    combined = ", ".join(part for part in (street, zip_city) if part)
    return combined or None


async def latest_invoice_id(session: AsyncSession, org_id: uuid.UUID) -> uuid.UUID | None:
    """The most recently numbered invoice — the only one that may be cancelled."""
    row = await session.scalar(
        select(TripInvoice.id)
        .where(TripInvoice.organization_id == org_id)
        .order_by(TripInvoice.number.desc())
        .limit(1)
    )
    return row


async def create_invoice(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    property_id: uuid.UUID,
    trip_ids: list[uuid.UUID],
    rate_cents_per_km: int,
    vat_percent: Decimal,
    issued_on: date | None,
    legal_basis: str | None,
    note: str | None,
) -> TripInvoice:
    """Validate the selection, snapshot the lines, number the invoice and mark
    the trips as billed. Flushes + commits."""
    prop = await session.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == org_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise TripInvoiceError("Objekt nicht gefunden")

    wanted = list(dict.fromkeys(trip_ids))  # de-dupe, keep order
    trips = list(
        (
            await session.scalars(
                select(Trip).where(Trip.id.in_(wanted), Trip.organization_id == org_id)
            )
        ).all()
    )
    by_id = {t.id: t for t in trips}
    missing = [str(i) for i in wanted if i not in by_id]
    if missing:
        raise TripInvoiceError(f"Fahrt nicht gefunden: {missing[0]}")
    for t in trips:
        if t.property_id != prop.id:
            raise TripInvoiceError("Fahrt gehört zu einem anderen Objekt")
        if t.status != TripStatus.CONFIRMED.value:
            raise TripInvoiceError("Fahrt ist noch nicht bestätigt")
        if t.purpose == TripPurpose.PRIVAT.value:
            raise TripInvoiceError("Private Fahrten können nicht berechnet werden")
        if not t.distance_m:
            raise TripInvoiceError("Fahrt ohne Strecke")
        if t.invoice_id is not None:
            raise TripInvoiceError("Fahrt ist bereits abgerechnet", status=409)

    trips.sort(key=lambda t: t.started_at)
    lines: list[dict[str, Any]] = []
    net = 0
    distance = 0
    for t in trips:
        amount = line_amount_cents(t.distance_m or 0, rate_cents_per_km)
        net += amount
        distance += t.distance_m or 0
        lines.append(
            {
                "trip_id": str(t.id),
                "date": t.started_at.astimezone(_BERLIN).date().isoformat(),
                "purpose": t.purpose,
                "distance_m": t.distance_m or 0,
                "amount_cents": amount,
                "note": t.note,
            }
        )
    vat = vat_cents(net, vat_percent)
    issued = issued_on or datetime.now(_BERLIN).date()
    rule = default_rule(prop.type)
    inv = TripInvoice(
        organization_id=org_id,
        property_id=prop.id,
        created_by_user_id=created_by_user_id,
        number=await next_number(session, org_id, issued.year),
        issued_on=issued,
        period_from=trips[0].started_at.astimezone(_BERLIN).date(),
        period_to=trips[-1].started_at.astimezone(_BERLIN).date(),
        rate_cents_per_km=rate_cents_per_km,
        vat_percent=vat_percent,
        trip_count=len(trips),
        distance_m=distance,
        net_cents=net,
        vat_cents=vat,
        gross_cents=net + vat,
        lines_json=lines,
        recipient_json={
            "name": prop.name,
            "address": property_address(prop),
            "type": prop.type.value,
        },
        legal_basis=(legal_basis or "").strip() or rule.legal_basis,
        note=(note or "").strip() or None,
    )
    session.add(inv)
    await session.flush()
    for t in trips:
        t.invoice_id = inv.id
    await session.commit()
    await session.refresh(inv)
    return inv


# --- PDF ----------------------------------------------------------------------


def _fit(text: str, width: float, size: float, font: str = _FONT) -> str:
    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


def _wrap(text: str, width: float, size: float, font: str = _FONT) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        probe = f"{cur} {w}".strip()
        if stringWidth(probe, font, size) <= width:
            cur = probe
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _de_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _de_percent(v: Decimal) -> str:
    s = f"{Decimal(v):.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") + " %"


def render_invoice_pdf(inv: TripInvoice, *, generated_at: datetime | None = None) -> bytes:
    """Render the invoice from its snapshot — pure function of the row."""
    page_w, page_h = (float(v) for v in A4)
    margin: float = float(20 * mm)
    content_w: float = page_w - 2 * margin
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Rechnung {inv.number} — Auslagenersatz Fahrtkosten")
    size = 9.5
    lead = 13.0

    def footer() -> None:
        y = margin - 4
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.setLineWidth(0.4)
        c.line(margin, y + 30, page_w - margin, y + 30)
        c.setFont(_FONT, 7)
        col = content_w / 3
        blocks = [
            [company.NAME, company.STREET, company.CITY, company.WEB],
            [company.REGISTER, company.MANAGING_DIRECTOR, f"Tel. {company.PHONE}"],
            [company.TAX_OFFICE, company.TAX_NO, company.VAT_ID],
        ]
        for i, lines in enumerate(blocks):
            yy = y + 22
            for ln in lines:
                c.drawString(margin + i * col, yy, ln)
                yy -= 8.5
        c.drawRightString(page_w - margin, y - 4, f"Seite {c.getPageNumber()}")

    def new_page() -> float:
        footer()
        c.showPage()
        c.setFont(_FONT, size)
        top: float = page_h - margin
        return top

    # Header: logo (or wordmark) right, sender line + recipient left.
    y = page_h - margin
    try:
        if _LOGO_PATH.exists():
            logo = ImageReader(str(_LOGO_PATH))
            lw, lh = 42 * mm, 42 * mm * 471 / 838
            c.drawImage(logo, page_w - margin - lw, y - lh, lw, lh, mask="auto")
    except Exception:  # pragma: no cover - never fail a render over the logo
        pass
    c.setFont(_FONT, 7.5)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawString(margin, y - 28 * mm, f"{company.NAME} · {company.STREET} · {company.CITY}")
    c.setFillColorRGB(0, 0, 0)
    c.setFont(_FONT, 10.5)
    rec = inv.recipient_json or {}
    ry = y - 34 * mm
    c.drawString(margin, ry, str(rec.get("name") or "—"))
    addr = str(rec.get("address") or "")
    for part in [p.strip() for p in addr.split(",") if p.strip()]:
        ry -= lead
        c.drawString(margin, ry, part)

    # Meta block right
    meta = [
        ("Rechnungsnummer", inv.number),
        ("Rechnungsdatum", _de_date(inv.issued_on)),
        (
            "Leistungszeitraum",
            f"{_de_date(inv.period_from)} bis {_de_date(inv.period_to)}"
            if inv.period_from != inv.period_to
            else _de_date(inv.period_from),
        ),
    ]
    my = y - 34 * mm
    for label, value in meta:
        c.setFont(_FONT, 8.5)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        c.drawRightString(page_w - margin - 54 * mm, my, label)
        c.setFillColorRGB(0, 0, 0)
        c.setFont(_BOLD, 9.5)
        c.drawRightString(page_w - margin, my, value)
        my -= lead

    # Title + intro
    y = y - 62 * mm
    c.setFont(_BOLD, 14)
    c.drawString(margin, y, "Rechnung — Auslagenersatz Fahrtkosten")
    y -= lead * 1.6
    c.setFont(_FONT, size)
    rate_txt = f"{Decimal(inv.rate_cents_per_km) / 100:.2f}".replace(".", ",")
    intro = (
        f"für das Objekt {rec.get('name') or '—'} berechnen wir die nachstehend aufgeführten "
        f"Fahrten mit {rate_txt} € je gefahrenem Kilometer."
    )
    for ln in _wrap("Sehr geehrte Damen und Herren,", content_w, size) + _wrap(
        intro, content_w, size
    ):
        c.drawString(margin, y, ln)
        y -= lead
    if inv.legal_basis:
        y -= lead * 0.3
        c.setFont(_FONT, 8.5)
        c.setFillColorRGB(0.3, 0.3, 0.3)
        for ln in _wrap(f"Grundlage: {inv.legal_basis}", content_w, 8.5):
            c.drawString(margin, y, ln)
            y -= 11
        c.setFillColorRGB(0, 0, 0)
    y -= lead * 0.8

    # Table
    cols = [
        ("Datum", 60, "left"),
        ("Zweck", 130, "left"),
        ("Notiz", content_w - 60 - 130 - 60 - 80, "left"),
        ("km", 60, "right"),
        ("Betrag (netto)", 80, "right"),
    ]

    def table_head(yy: float) -> float:
        c.setFillColorRGB(0.93, 0.93, 0.93)
        c.rect(margin, yy - 4, content_w, 14, fill=1, stroke=0)
        c.setFillColorRGB(0, 0, 0)
        c.setFont(_BOLD, size)
        x = margin
        for title, w, align in cols:
            if align == "right":
                c.drawRightString(x + w - 3, yy, title)
            else:
                c.drawString(x + 3, yy, title)
            x += w
        return yy - lead - 3

    y = table_head(y)
    c.setFont(_FONT, size)
    for line in inv.lines_json or []:
        if y < margin + 60:
            y = new_page()
            y = table_head(y)
            c.setFont(_FONT, size)
        d = date.fromisoformat(str(line.get("date")))
        cells = [
            _de_date(d),
            _fit(_PURPOSE_LABEL.get(str(line.get("purpose") or ""), "—"), cols[1][1] - 6, size),
            _fit(str(line.get("note") or ""), cols[2][1] - 6, size),
            de_km(int(line.get("distance_m") or 0)),
            de_money(int(line.get("amount_cents") or 0)),
        ]
        x = margin
        for (_t, w, align), txt in zip(cols, cells, strict=True):
            if align == "right":
                c.drawRightString(x + w - 3, y, txt)
            else:
                c.drawString(x + 3, y, txt)
            x += w
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setLineWidth(0.3)
        c.line(margin, y - 3.5, margin + content_w, y - 3.5)
        y -= lead

    # Totals
    if y < margin + 90:
        y = new_page()
    y -= 4
    right = margin + content_w
    label_x = right - 80 - 3
    totals = [
        (
            f"Zwischensumme ({inv.trip_count} Fahrten, {de_km(inv.distance_m)})",
            de_money(inv.net_cents),
            False,
        ),
        (f"zzgl. {_de_percent(inv.vat_percent)} USt", de_money(inv.vat_cents), False),
        ("Rechnungsbetrag", de_money(inv.gross_cents), True),
    ]
    for label, value, bold in totals:
        c.setFont(_BOLD if bold else _FONT, size + (1 if bold else 0))
        c.drawRightString(label_x - 60, y, label)
        c.drawRightString(right - 3, y, value)
        y -= lead
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.6)
    c.line(label_x - 60 - 160, y + lead - 4, right, y + lead - 4)

    y -= lead
    c.setFont(_FONT, size)
    closing = [
        "Der Rechnungsbetrag wird dem Konto des Objekts belastet; "
        "eine Überweisung ist nicht erforderlich.",
        "Die Einzelnachweise der Fahrten (Datum, Strecke, Route) liegen im "
        "Fahrtenbuch der Verwaltung vor.",
    ]
    if inv.note:
        closing.append(inv.note)
    for para in closing:
        for ln in _wrap(para, content_w, size):
            if y < margin + 50:
                y = new_page()
            c.drawString(margin, y, ln)
            y -= lead
        y -= lead * 0.4
    y -= lead * 0.5
    c.drawString(margin, y, "Mit freundlichen Grüßen")
    y -= lead * 1.8
    c.drawString(margin, y, company.NAME)

    stamp = (generated_at or datetime.now(_BERLIN)).strftime("%d.%m.%Y %H:%M")
    c.setFont(_FONT, 6.5)
    c.setFillColorRGB(0.55, 0.55, 0.55)
    c.drawString(margin, margin - 24, f"Erstellt {stamp} · Belegnummer {inv.number}")
    c.setFillColorRGB(0, 0, 0)
    footer()
    c.showPage()
    c.save()
    return buf.getvalue()


def invoice_filename(inv: TripInvoice) -> str:
    return f"Rechnung-{inv.number}.pdf"


__all__ = [
    "BillingRule",
    "TripInvoiceError",
    "billable_filter",
    "create_invoice",
    "default_rule",
    "invoice_filename",
    "latest_invoice_id",
    "line_amount_cents",
    "next_number",
    "property_address",
    "render_invoice_pdf",
    "vat_cents",
]
