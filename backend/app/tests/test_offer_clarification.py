"""anfragen@ clarification round-trip.

Until 2026-08-21 an inquiry whose contract type could not be extracted
(art=UNKNOWN) ended in NEEDS_REVIEW and nothing else happened: the prospect
got silence and the Verwalter no notice. These cover the two halves of the
fix — asking back, and turning the answer into an offer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.integrations.email.offer_clarification import (
    render_clarification_email,
    render_review_notice,
)
from app.models import OfferInquiry, OfferInquiryStatus, UserRole
from app.services import offers as offers_svc
from app.tests._factories import make_org, make_user


class _Recorder:
    """Stands in for EmailClient; records sends, returns a message id."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = fail

    async def send(self, **kw: Any) -> str:
        if self.fail:
            raise RuntimeError("provider down")
        self.sent.append(kw)
        return f"msg-{len(self.sent)}"


class _Settings:
    offer_from_address = "anfragen@wagner-hausverwaltung.com"
    offer_from_name = "Wagner Hausverwaltung"
    anfragen_inbound_address = "anfragen@wagner-hausverwaltung.com"


async def _make_inquiry(sm: Any, org_id: Any, **kw: Any) -> OfferInquiry:
    async with sm() as s:
        inq = OfferInquiry(
            organization_id=org_id,
            sender_email=kw.get("sender_email", "interessent@example.de"),
            subject=kw.get("subject", "Angebot vorbereiten"),
            body=kw.get("body", "In Summe 18 Einheiten\nFlößerstrasse 63"),
            status=OfferInquiryStatus.EXTRACTED.value,
            units=kw.get("units", 18),
            object_address=kw.get("object_address", "Flößerstrasse 63, 74321 Bissingen"),
            art=kw.get("art"),
        )
        s.add(inq)
        await s.commit()
        await s.refresh(inq)
        return inq


def test_clarification_email_asks_the_one_open_question() -> None:
    subject, html, text = render_clarification_email(subject="Angebot vorbereiten")
    assert "Angebot vorbereiten" in subject
    for body in (html, text):
        assert "WEG" in body
        assert "Mietverwaltung" in body
    # A single question — no form to fill in, or people won't reply.
    assert text.count("?") == 1


def test_review_notice_states_whether_the_sender_was_asked() -> None:
    _s, _h, asked = render_review_notice(
        sender_email="a@b.de", subject="X", units=18, object_address="Y", asked_back=True
    )
    _s2, _h2, quiet = render_review_notice(
        sender_email="a@b.de", subject="X", units=18, object_address="Y", asked_back=False
    )
    assert "sobald er antwortet" in asked
    assert "KEINE automatische Rückfrage" in quiet


async def test_unbuildable_inquiry_asks_sender_and_notifies_verwalter(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    _v, v_email, _pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    inq = await _make_inquiry(sm, org.id)

    client = _Recorder()
    async with sm() as s:
        row = await s.get(OfferInquiry, inq.id)
        assert row is not None
        outcome = await offers_svc.handle_unsendable_inquiry(
            s, row, email_client=client, settings=_Settings(), can_build=False
        )
        await s.commit()

    assert outcome == "asked_back"
    to = [m["to"] for m in client.sent]
    assert "interessent@example.de" in to  # the prospect was asked
    assert v_email in to  # the Verwalter was told
    # Replies must land back on anfragen@, not on a no-reply address.
    ask = next(m for m in client.sent if m["to"] == "interessent@example.de")
    assert ask["reply_to"] == _Settings.anfragen_inbound_address

    async with sm() as s:
        row = await s.get(OfferInquiry, inq.id)
        assert row is not None
        assert row.clarification_sent_at is not None
        assert row.clarification_message_id == "msg-1"


async def test_policy_block_notifies_verwalter_but_does_not_pester_sender(
    test_engine: AsyncEngine,
) -> None:
    """Auto-Modus off is OUR decision — the sender has nothing to answer."""
    org = await make_org(test_engine)
    _v, v_email, _pw = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    inq = await _make_inquiry(sm, org.id, art="WEG")

    client = _Recorder()
    async with sm() as s:
        row = await s.get(OfferInquiry, inq.id)
        assert row is not None
        outcome = await offers_svc.handle_unsendable_inquiry(
            s, row, email_client=client, settings=_Settings(), can_build=True
        )
        await s.commit()

    assert outcome == "notified_only"
    assert [m["to"] for m in client.sent] == [v_email]


async def test_sender_is_asked_only_once(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    inq = await _make_inquiry(sm, org.id)

    client = _Recorder()
    for _ in range(2):
        async with sm() as s:
            row = await s.get(OfferInquiry, inq.id)
            assert row is not None
            await offers_svc.handle_unsendable_inquiry(
                s, row, email_client=client, settings=_Settings(), can_build=False
            )
            await s.commit()

    asks = [m for m in client.sent if m["to"] == "interessent@example.de"]
    assert len(asks) == 1


async def test_send_failure_never_breaks_the_pipeline(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    inq = await _make_inquiry(sm, org.id)

    async with sm() as s:
        row = await s.get(OfferInquiry, inq.id)
        assert row is not None
        outcome = await offers_svc.handle_unsendable_inquiry(
            s, row, email_client=_Recorder(fail=True), settings=_Settings(), can_build=False
        )
        await s.commit()

    assert outcome == "notified_only"
    async with sm() as s:
        row = await s.get(OfferInquiry, inq.id)
        assert row is not None
        # Not stamped — so a later run can retry the question.
        assert row.clarification_sent_at is None


async def test_extraction_json_with_unknown_art_yields_no_offer_request(
    test_engine: AsyncEngine,
) -> None:
    """Regression guard for the real 2026-08-20 payload: art=UNKNOWN must not
    silently become a WEG offer."""
    from app.services import offer_extraction

    org = await make_org(test_engine)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    inq = await _make_inquiry(sm, org.id)
    async with sm() as s:
        row = await s.get(OfferInquiry, inq.id)
        assert row is not None
        row.extraction_json = json.dumps(
            {
                "is_offer_request": True,
                "art": "UNKNOWN",
                "units": 18,
                "object_street": "Flößerstrasse 63",
                "object_plz_city": "74321 Bissingen",
                "confidence": 0.6,
            }
        )
        await s.commit()
        assert offer_extraction.build_offer_request(row) is None


async def test_clarification_window_expires(test_engine: AsyncEngine) -> None:
    """A reply months later belongs to a new inquiry, not a stale one."""
    org = await make_org(test_engine)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    inq = await _make_inquiry(sm, org.id)
    async with sm() as s:
        row = await s.get(OfferInquiry, inq.id)
        assert row is not None
        row.status = OfferInquiryStatus.NEEDS_REVIEW.value
        row.clarification_sent_at = datetime.now(UTC) - timedelta(days=45)
        row.clarification_message_id = "old-msg"
        await s.commit()

    from app.api.v1.webhooks import _match_clarification_reply

    class _Parsed:
        sender_email = "interessent@example.de"
        in_reply_to = None
        references = None
        body = "WEG"

    async with sm() as s:
        assert await _match_clarification_reply(s, _Parsed()) is None


async def test_reply_within_window_matches_by_sender(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    inq = await _make_inquiry(sm, org.id, sender_email="neu@example.de")
    async with sm() as s:
        row = await s.get(OfferInquiry, inq.id)
        assert row is not None
        row.status = OfferInquiryStatus.NEEDS_REVIEW.value
        row.clarification_sent_at = datetime.now(UTC) - timedelta(hours=2)
        row.clarification_message_id = "msg-x"
        await s.commit()

    from app.api.v1.webhooks import _match_clarification_reply

    class _Parsed:
        sender_email = "NEU@example.de"  # case-insensitive on purpose
        in_reply_to = None
        references = None
        body = "Es geht um eine WEG"

    async with sm() as s:
        hit = await _match_clarification_reply(s, _Parsed())
        assert hit is not None and hit.id == inq.id

    # And an unrelated sender must not match it.
    class _Other:
        sender_email = "fremd@example.de"
        in_reply_to = None
        references = None
        body = "WEG"

    async with sm() as s:
        assert await _match_clarification_reply(s, _Other()) is None


async def test_sent_inquiry_is_never_reopened_by_a_later_mail(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    inq = await _make_inquiry(sm, org.id, sender_email="kunde@example.de")
    async with sm() as s:
        row = await s.get(OfferInquiry, inq.id)
        assert row is not None
        row.status = OfferInquiryStatus.NEEDS_REVIEW.value
        row.clarification_sent_at = datetime.now(UTC)
        row.sent_at = datetime.now(UTC)  # offer already went out
        await s.commit()

    from app.api.v1.webhooks import _match_clarification_reply

    class _Parsed:
        sender_email = "kunde@example.de"
        in_reply_to = None
        references = None
        body = "Danke!"

    async with sm() as s:
        assert await _match_clarification_reply(s, _Parsed()) is None


async def test_unrelated_inquiries_are_untouched(test_engine: AsyncEngine) -> None:
    """Sanity: an inquiry we never asked about is not a merge target."""
    org = await make_org(test_engine)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    await _make_inquiry(sm, org.id, sender_email="still@example.de")

    from app.api.v1.webhooks import _match_clarification_reply

    class _Parsed:
        sender_email = "still@example.de"
        in_reply_to = None
        references = None
        body = "WEG"

    async with sm() as s:
        assert await _match_clarification_reply(s, _Parsed()) is None
        # Scoped to this org — the session-wide test DB keeps rows from the
        # other cases in this file, which deliberately DO carry a stamp.
        rows = (
            await s.scalars(select(OfferInquiry).where(OfferInquiry.organization_id == org.id))
        ).all()
        assert rows and all(r.clarification_sent_at is None for r in rows)
