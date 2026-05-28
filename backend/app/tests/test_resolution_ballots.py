"""Email-voting for Umlaufbeschlüsse: ballots split owners with/without
email, and the public token endpoint records a one-shot vote without a
portal account."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.integrations.email.client import EmailClient
from app.main import app
from app.models import (
    CircularResolution,
    CircularVote,
    ResolutionBallot,
    ResolutionMode,
    ResolutionStatus,
)
from app.services.circular import (
    eligible_owners,
    generate_ballots,
    send_ballot_invitations,
)
from app.tests._factories import make_contact_with_contract_link, make_org, make_property


def _uid() -> int:
    return uuid.uuid4().int % 9_000_000_000_000_000


class _RecordingEmail:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, *, to: str, subject: str, html: str, text: str, **kwargs: Any) -> str:
        self.sent.append(to)
        return "rec-id"


async def _make_resolution(
    sm: async_sessionmaker[Any], *, org_id: uuid.UUID, property_id: uuid.UUID
) -> uuid.UUID:
    async with sm() as s:
        now = datetime.now(UTC)
        r = CircularResolution(
            organization_id=org_id,
            property_id=property_id,
            title="Dachsanierung",
            description="Beschluss über die Dachsanierung.",
            mode=ResolutionMode.MEHRHEITS,
            status=ResolutionStatus.OFFEN,
            opens_at=now - timedelta(hours=1),
            closes_at=now + timedelta(days=14),
            required_quorum=0,
        )
        s.add(r)
        await s.commit()
        await s.refresh(r)
    return r.id


async def test_ballots_split_owners_by_email(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    c_with, c_without = _uid(), _uid()
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c_with, contact_email="owner@example.de"
    )
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c_without, contact_email=None
    )
    rid = await _make_resolution(sm, org_id=org.id, property_id=prop.id)

    recorder = _RecordingEmail()
    async with sm() as s:
        r = await s.get(CircularResolution, rid)
        assert r is not None
        owners = await eligible_owners(s, org.id, prop.id)
        assert {o.contact_id_impower for o in owners} == {c_with, c_without}
        created = await generate_ballots(s, r)
        await s.commit()
        assert len(created) == 2
        sent, no_email = await send_ballot_invitations(s, r, cast(EmailClient, recorder))
        await s.commit()

    assert sent == 1
    assert recorder.sent == ["owner@example.de"]
    assert {b.owner_contact_id_impower for b in no_email} == {c_without}


async def test_public_ballot_vote_is_one_shot(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    c = _uid()
    await make_contact_with_contract_link(
        test_engine, org=org, prop=prop, contact_impower_id=c, contact_email="o@example.de"
    )
    rid = await _make_resolution(sm, org_id=org.id, property_id=prop.id)
    async with sm() as s:
        r = await s.get(CircularResolution, rid)
        assert r is not None
        await generate_ballots(s, r)
        await s.commit()
        ballot = await s.scalar(
            select(ResolutionBallot).where(ResolutionBallot.resolution_id == rid)
        )
        assert ballot is not None
        token = ballot.token

    with TestClient(app) as client:
        g = client.get(f"/public/resolutions/ballot/{token}")
        assert g.status_code == 200
        body = g.json()
        assert body["resolution_title"] == "Dachsanierung"
        assert body["already_voted"] is False
        assert body["open_for_voting"] is True

        v = client.post(f"/public/resolutions/ballot/{token}/vote", json={"choice": "JA"})
        assert v.status_code == 201
        assert v.json()["already_voted"] is True

        # One-shot: a second attempt is rejected.
        v2 = client.post(f"/public/resolutions/ballot/{token}/vote", json={"choice": "NEIN"})
        assert v2.status_code == 409

        # Unknown token → 404, no info leak.
        assert client.get("/public/resolutions/ballot/does-not-exist").status_code == 404

    async with sm() as s:
        votes = (
            await s.scalars(select(CircularVote).where(CircularVote.resolution_id == rid))
        ).all()
    assert len(votes) == 1
    assert votes[0].choice.value == "JA"
    assert votes[0].signature_method == "EMAIL_TOKEN"
    assert votes[0].voter_user_id is None
