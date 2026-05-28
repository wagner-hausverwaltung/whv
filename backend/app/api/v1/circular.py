"""Umlaufbeschluss API.

Two routers in one file because they share the tally + eligibility helpers:
  /me/resolutions/...     — Eigentümer: list visible resolutions, vote
  /admin/resolutions/...  — Verwalter: create, close early, see live quorum

Eligibility model: an owner is eligible to vote on a resolution iff they hold
an OWNER contract on the resolution's property (joined via contact_contacts).
This excludes Mieter — only Eigentümer vote on WEG matters.
"""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.db import get_session
from app.integrations.email.client import EmailClient, get_email_client
from app.models import (
    AuditLog,
    CircularResolution,
    CircularVote,
    Contact,
    Contract,
    ContractContact,
    ContractType,
    Property,
    ResolutionBallot,
    ResolutionMode,
    ResolutionStatus,
    User,
    UserRole,
    VoteChoice,
)
from app.schemas.circular import (
    BallotStatus,
    CreateResolutionRequest,
    ManualVoteRequest,
    ResolutionDetailResponse,
    ResolutionResponse,
    ResolutionTally,
    UpdateResolutionRequest,
    VoteRequest,
    VoteResponse,
)
from app.services.circular import (
    finalize_resolution,
    generate_ballots,
    resolve_result_pdf_path,
    send_ballot_invitations,
)

me_router = APIRouter(prefix="/me/resolutions", tags=["resolutions"])
admin_router = APIRouter(prefix="/admin/resolutions", tags=["resolutions"])
# Unauthenticated — owners vote by email via a long random ballot token,
# no portal account required. The token (256-bit) is the only credential
# and exposes exactly one resolution + one vote.
public_router = APIRouter(prefix="/public/resolutions", tags=["resolutions-public"])

_verwalter_only = require_role(UserRole.VERWALTER)


# --- Eligibility helpers -----------------------------------------------------


async def _eligible_owner_impower_ids(
    session: AsyncSession,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
) -> set[int]:
    """Return Impower contact IDs of every owner eligible to vote on this property.

    Eligible == active OWNER contract (not Mieter / not soft-deleted) →
    contract_contacts junction → contact.impower_id. Distinct.
    """
    rows = (
        await session.scalars(
            select(Contact.impower_id)
            .join(ContractContact, ContractContact.contact_id == Contact.id)
            .join(Contract, Contract.id == ContractContact.contract_id)
            .where(
                Contract.organization_id == organization_id,
                Contract.property_id == property_id,
                Contract.type == ContractType.OWNER,
                Contract.deleted_at.is_(None),
                Contact.deleted_at.is_(None),
                Contact.impower_id.is_not(None),
            )
            .distinct()
        )
    ).all()
    return {int(r) for r in rows if r is not None}


async def _eligible_owner_emails(
    session: AsyncSession,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
) -> list[str]:
    """Return emails of registered WHV users that are eligible owners.

    Used to fan out the resolution-invitation email. Owners without a
    WHV-Portal account (no users.contact_id_impower match) are excluded —
    Phase 4-iter2 will add ePost / WhatsApp paths for them.
    """
    eligible_impower_ids = await _eligible_owner_impower_ids(session, organization_id, property_id)
    if not eligible_impower_ids:
        return []
    rows = (
        await session.scalars(
            select(User.email).where(
                User.organization_id == organization_id,
                User.contact_id_impower.in_(eligible_impower_ids),
                User.deleted_at.is_(None),
            )
        )
    ).all()
    return list(rows)


async def _tally(
    session: AsyncSession,
    resolution: CircularResolution,
) -> ResolutionTally:
    eligible = await _eligible_owner_impower_ids(
        session, resolution.organization_id, resolution.property_id
    )
    votes = (
        await session.scalars(
            select(CircularVote).where(CircularVote.resolution_id == resolution.id)
        )
    ).all()
    ja = sum(1 for v in votes if v.choice == VoteChoice.JA)
    nein = sum(1 for v in votes if v.choice == VoteChoice.NEIN)
    enth = sum(1 for v in votes if v.choice == VoteChoice.ENTHALTUNG)
    cast = ja + nein + enth
    voted_ids = {v.owner_contact_id_impower for v in votes}
    # KLASSISCH (Allstimmigkeit): every eligible owner has voted AND every
    # vote is JA. Missing votes don't count as anything — they're failures.
    unanimous = bool(eligible) and eligible.issubset(voted_ids) and nein == 0 and enth == 0
    return ResolutionTally(
        eligible_voters=len(eligible),
        cast=cast,
        ja=ja,
        nein=nein,
        enthaltung=enth,
        quorum_met=cast >= resolution.required_quorum,
        unanimous_yes=unanimous,
    )


def _decide_outcome(mode: ResolutionMode, tally: ResolutionTally) -> ResolutionStatus:
    """Pure function — given mode + tally, return ANGENOMMEN or ABGELEHNT."""
    if mode == ResolutionMode.KLASSISCH:
        return ResolutionStatus.ANGENOMMEN if tally.unanimous_yes else ResolutionStatus.ABGELEHNT
    # MEHRHEITS: quorum must be met AND strict majority of cast votes are JA
    if not tally.quorum_met:
        return ResolutionStatus.ABGELEHNT
    return ResolutionStatus.ANGENOMMEN if tally.ja > tally.cast / 2 else ResolutionStatus.ABGELEHNT


def _summarize_result(tally: ResolutionTally, status: ResolutionStatus) -> str:
    return (
        f"{tally.ja} JA · {tally.nein} NEIN · {tally.enthaltung} Enthaltung "
        f"(von {tally.eligible_voters} stimmberechtigt) — {status.value}"
    )


# --- Conversion helpers ------------------------------------------------------


def _to_summary(r: CircularResolution) -> ResolutionResponse:
    return ResolutionResponse.model_validate(r)


def _to_detail(
    r: CircularResolution,
    votes: list[CircularVote],
    tally: ResolutionTally,
    *,
    my_impower_id: int | None,
    am_eligible: bool,
    include_all_votes: bool,
) -> ResolutionDetailResponse:
    visible_votes: list[CircularVote] = (
        votes
        if include_all_votes
        else [v for v in votes if v.owner_contact_id_impower == my_impower_id]
    )
    my_vote_obj: CircularVote | None = next(
        (v for v in votes if v.owner_contact_id_impower == my_impower_id), None
    )
    return ResolutionDetailResponse(
        id=r.id,
        property_id=r.property_id,
        title=r.title,
        mode=r.mode,
        status=r.status,
        opens_at=r.opens_at,
        closes_at=r.closes_at,
        required_quorum=r.required_quorum,
        decided_at=r.decided_at,
        created_at=r.created_at,
        description=r.description,
        pdf_url=r.pdf_url,
        result_pdf_url=r.result_pdf_url,
        result=r.result,
        tally=tally,
        votes=[VoteResponse.model_validate(v) for v in visible_votes],
        my_vote=VoteResponse.model_validate(my_vote_obj) if my_vote_obj else None,
        am_eligible=am_eligible,
    )


# --- Owner endpoints ---------------------------------------------------------


@me_router.get("", response_model=list[ResolutionResponse])
async def list_my_resolutions(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ResolutionResponse]:
    """Resolutions on properties where the caller has an OWNER contract.

    Includes ENTWURF (Verwalter is still drafting → owner won't see those —
    filtered below), OFFEN (votable), and decided states for history.
    """
    if current_user.contact_id_impower is None:
        return []
    # Properties where the user has an active OWNER contract.
    visible_properties = (
        await session.scalars(
            select(Property.id)
            .join(Contract, Contract.property_id == Property.id)
            .join(ContractContact, ContractContact.contract_id == Contract.id)
            .join(Contact, Contact.id == ContractContact.contact_id)
            .where(
                Property.organization_id == current_user.organization_id,
                Property.deleted_at.is_(None),
                Contract.type == ContractType.OWNER,
                Contract.deleted_at.is_(None),
                Contact.impower_id == current_user.contact_id_impower,
                Contact.deleted_at.is_(None),
            )
            .distinct()
        )
    ).all()
    if not visible_properties:
        return []
    rows = (
        await session.scalars(
            select(CircularResolution)
            .where(
                CircularResolution.organization_id == current_user.organization_id,
                CircularResolution.property_id.in_(visible_properties),
                CircularResolution.status != ResolutionStatus.ENTWURF,
            )
            .order_by(CircularResolution.closes_at.desc())
        )
    ).all()
    return [_to_summary(r) for r in rows]


async def _load_resolution_for_owner(
    session: AsyncSession, user: User, resolution_id: uuid.UUID
) -> CircularResolution:
    if user.contact_id_impower is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resolution not found")
    r = await session.scalar(
        select(CircularResolution).where(
            CircularResolution.id == resolution_id,
            CircularResolution.organization_id == user.organization_id,
        )
    )
    if r is None or r.status == ResolutionStatus.ENTWURF:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resolution not found")
    eligible = await _eligible_owner_impower_ids(session, user.organization_id, r.property_id)
    if user.contact_id_impower not in eligible:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resolution not found")
    return r


@me_router.get("/{resolution_id}", response_model=ResolutionDetailResponse)
async def get_my_resolution(
    resolution_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ResolutionDetailResponse:
    r = await _load_resolution_for_owner(session, current_user, resolution_id)
    votes = list(
        (
            await session.scalars(
                select(CircularVote)
                .where(CircularVote.resolution_id == r.id)
                .order_by(CircularVote.voted_at)
            )
        ).all()
    )
    tally = await _tally(session, r)
    return _to_detail(
        r,
        votes,
        tally,
        my_impower_id=current_user.contact_id_impower,
        am_eligible=True,
        include_all_votes=False,  # owners only see their own vote
    )


@me_router.post(
    "/{resolution_id}/vote",
    response_model=VoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def cast_my_vote(
    resolution_id: uuid.UUID,
    req: VoteRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VoteResponse:
    r = await _load_resolution_for_owner(session, current_user, resolution_id)
    now = datetime.now(UTC)
    if r.status != ResolutionStatus.OFFEN or now >= r.closes_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Abstimmung ist nicht (mehr) offen.",
        )

    # IP hashing — keep audit-grade evidence without storing raw IP (DSGVO).
    client_host = request.client.host if request.client else ""
    ip_hash = hashlib.sha256((client_host + str(r.id)).encode("utf-8")).hexdigest()[:32]
    evidence: dict[str, Any] = {
        "ip_hash": ip_hash,
        "user_agent": request.headers.get("user-agent", "")[:200],
    }

    # Upsert on (resolution_id, owner_contact_id_impower). One vote per owner.
    # Owners can change their mind until close.
    existing = await session.scalar(
        select(CircularVote).where(
            CircularVote.resolution_id == r.id,
            CircularVote.owner_contact_id_impower == current_user.contact_id_impower,
        )
    )
    if existing is not None:
        existing.choice = req.choice
        existing.voted_at = now
        existing.voter_user_id = current_user.id
        existing.evidence_jsonb = evidence
        vote = existing
    else:
        vote = CircularVote(
            resolution_id=r.id,
            owner_contact_id_impower=current_user.contact_id_impower,
            choice=req.choice,
            voter_user_id=current_user.id,
            signature_method="PORTAL_CLICK",
            evidence_jsonb=evidence,
        )
        session.add(vote)

    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="resolution_voted",
            target_type="circular_resolutions",
            target_id=str(r.id),
            payload_json={
                "choice": req.choice.value,
                "owner_contact_id_impower": current_user.contact_id_impower,
                "replaced": existing is not None,
            },
        )
    )
    await session.commit()
    await session.refresh(vote)
    return VoteResponse.model_validate(vote)


# --- Admin endpoints ---------------------------------------------------------


@admin_router.post(
    "",
    response_model=ResolutionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_resolution(
    req: CreateResolutionRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
) -> ResolutionDetailResponse:
    # Validate property in org
    prop = await session.scalar(
        select(Property).where(
            Property.id == req.property_id,
            Property.organization_id == current_user.organization_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    if req.closes_at <= req.opens_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="closes_at muss nach opens_at liegen.",
        )

    now = datetime.now(UTC)
    initial_status = ResolutionStatus.OFFEN if req.opens_at <= now else ResolutionStatus.ENTWURF

    resolution = CircularResolution(
        organization_id=current_user.organization_id,
        property_id=req.property_id,
        title=req.title,
        description=req.description,
        mode=req.mode,
        status=initial_status,
        opens_at=req.opens_at,
        closes_at=req.closes_at,
        required_quorum=req.required_quorum,
        created_by=current_user.id,
        opens_on=req.opens_at.date(),
        closes_on=req.closes_at.date(),
    )
    session.add(resolution)
    await session.flush()

    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="resolution_created",
            target_type="circular_resolutions",
            target_id=str(resolution.id),
            payload_json={
                "property_id": str(req.property_id),
                "mode": req.mode.value,
                "status": initial_status.value,
            },
        )
    )

    # If it opens immediately, fan out via ballots — reaches EVERY
    # eligible owner (registered or not) with a no-login voting link, not
    # just portal accounts. A draft (opens_at in future) waits for the
    # explicit "Jetzt versenden" action. Best-effort send.
    if initial_status == ResolutionStatus.OFFEN:
        await generate_ballots(session, resolution)
        await session.flush()
        await send_ballot_invitations(session, resolution, email_client)

    await session.commit()
    await session.refresh(resolution)
    tally = await _tally(session, resolution)
    return _to_detail(
        resolution,
        votes=[],
        tally=tally,
        my_impower_id=None,
        am_eligible=False,
        include_all_votes=True,
    )


class NoEmailOwner(BaseModel):
    owner_contact_id_impower: int
    owner_name: str | None


class ResolutionSendResponse(BaseModel):
    status: str
    sent: int
    no_email: list[NoEmailOwner]


@admin_router.post("/{resolution_id}/send", response_model=ResolutionSendResponse)
async def send_resolution(
    resolution_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
) -> ResolutionSendResponse:
    """ "Jetzt versenden": open a draft (if needed), materialise ballots
    for every eligible owner, and email the no-login voting link to each
    one that has an address. Returns the count sent + the owners WITHOUT
    an email (the Verwalter's postal-vote list). Idempotent — re-sending
    only mails ballots not yet sent."""
    r = await session.scalar(
        select(CircularResolution).where(
            CircularResolution.id == resolution_id,
            CircularResolution.organization_id == current_user.organization_id,
        )
    )
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resolution not found")
    if r.status not in (ResolutionStatus.ENTWURF, ResolutionStatus.OFFEN):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Beschluss ist bereits geschlossen.",
        )

    now = datetime.now(UTC)
    if r.status == ResolutionStatus.ENTWURF:
        r.status = ResolutionStatus.OFFEN
        if r.opens_at > now:
            r.opens_at = now

    await generate_ballots(session, r)
    await session.flush()
    sent, no_email = await send_ballot_invitations(session, r, email_client)

    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="resolution_sent",
            target_type="circular_resolutions",
            target_id=str(r.id),
            payload_json={"sent": sent, "no_email": len(no_email)},
        )
    )
    await session.commit()
    return ResolutionSendResponse(
        status=r.status.value,
        sent=sent,
        no_email=[
            NoEmailOwner(
                owner_contact_id_impower=b.owner_contact_id_impower,
                owner_name=b.owner_name,
            )
            for b in no_email
        ],
    )


@admin_router.patch("/{resolution_id}", response_model=ResolutionDetailResponse)
async def update_resolution(
    resolution_id: uuid.UUID,
    req: UpdateResolutionRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ResolutionDetailResponse:
    """Edit a DRAFT resolution. Only ENTWURF is editable — once it's
    been sent/opened, changing the text would invalidate cast votes."""
    r = await session.scalar(
        select(CircularResolution).where(
            CircularResolution.id == resolution_id,
            CircularResolution.organization_id == current_user.organization_id,
        )
    )
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resolution not found")
    if r.status != ResolutionStatus.ENTWURF:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nur Entwürfe können bearbeitet werden.",
        )
    if req.title is not None:
        r.title = req.title
    if req.description is not None:
        r.description = req.description
    if req.mode is not None:
        r.mode = req.mode
    if req.opens_at is not None:
        r.opens_at = req.opens_at
        r.opens_on = req.opens_at.date()
    if req.closes_at is not None:
        r.closes_at = req.closes_at
        r.closes_on = req.closes_at.date()
    if req.required_quorum is not None:
        r.required_quorum = req.required_quorum
    if r.closes_at <= r.opens_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="closes_at muss nach opens_at liegen.",
        )
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="resolution_updated",
            target_type="circular_resolutions",
            target_id=str(r.id),
            payload_json={},
        )
    )
    await session.commit()
    await session.refresh(r)
    tally = await _tally(session, r)
    return _to_detail(
        r,
        votes=[],
        tally=tally,
        my_impower_id=None,
        am_eligible=False,
        include_all_votes=True,
    )


@admin_router.get("/{resolution_id}/ballots", response_model=list[BallotStatus])
async def list_ballots(
    resolution_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[BallotStatus]:
    """Per-owner voting status — drives the admin no-email + paper-vote
    list. Reflects votes cast through any channel (portal/email/paper)."""
    r = await session.scalar(
        select(CircularResolution).where(
            CircularResolution.id == resolution_id,
            CircularResolution.organization_id == current_user.organization_id,
        )
    )
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resolution not found")
    ballots = (
        await session.scalars(
            select(ResolutionBallot).where(ResolutionBallot.resolution_id == r.id)
        )
    ).all()
    votes = (
        await session.scalars(select(CircularVote).where(CircularVote.resolution_id == r.id))
    ).all()
    by_owner = {v.owner_contact_id_impower: v for v in votes}
    out: list[BallotStatus] = []
    for b in sorted(ballots, key=lambda x: (x.owner_email is not None, x.owner_name or "")):
        v = by_owner.get(b.owner_contact_id_impower)
        out.append(
            BallotStatus(
                owner_contact_id_impower=b.owner_contact_id_impower,
                owner_name=b.owner_name,
                owner_email=b.owner_email,
                has_voted=b.voted_at is not None or v is not None,
                choice=v.choice if v else None,
            )
        )
    return out


@admin_router.post("/{resolution_id}/manual-vote", response_model=BallotStatus)
async def manual_vote(
    resolution_id: uuid.UUID,
    req: ManualVoteRequest,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BallotStatus:
    """Record a postal/paper vote on an owner's behalf (for owners
    without email). One-shot per owner, same as the email path."""
    r = await session.scalar(
        select(CircularResolution).where(
            CircularResolution.id == resolution_id,
            CircularResolution.organization_id == current_user.organization_id,
        )
    )
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resolution not found")
    now = datetime.now(UTC)
    if r.status != ResolutionStatus.OFFEN or now >= r.closes_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Abstimmung ist nicht (mehr) offen.",
        )
    eligible = await _eligible_owner_impower_ids(session, r.organization_id, r.property_id)
    if req.owner_contact_id_impower not in eligible:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Eigentümer ist nicht stimmberechtigt.",
        )
    existing = await session.scalar(
        select(CircularVote).where(
            CircularVote.resolution_id == r.id,
            CircularVote.owner_contact_id_impower == req.owner_contact_id_impower,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Für diesen Eigentümer wurde bereits abgestimmt.",
        )
    session.add(
        CircularVote(
            resolution_id=r.id,
            owner_contact_id_impower=req.owner_contact_id_impower,
            choice=req.choice,
            voter_user_id=None,
            signature_method="PAPER",
            evidence_jsonb={"recorded_by": str(current_user.id)},
        )
    )
    ballot = await session.scalar(
        select(ResolutionBallot).where(
            ResolutionBallot.resolution_id == r.id,
            ResolutionBallot.owner_contact_id_impower == req.owner_contact_id_impower,
        )
    )
    if ballot is not None:
        ballot.voted_at = now
    session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="resolution_manual_vote",
            target_type="circular_resolutions",
            target_id=str(r.id),
            payload_json={
                "owner_contact_id_impower": req.owner_contact_id_impower,
                "choice": req.choice.value,
            },
        )
    )
    await session.commit()
    return BallotStatus(
        owner_contact_id_impower=req.owner_contact_id_impower,
        owner_name=ballot.owner_name if ballot else None,
        owner_email=ballot.owner_email if ballot else None,
        has_voted=True,
        choice=req.choice,
    )


@admin_router.get("", response_model=list[ResolutionResponse])
async def list_all_resolutions(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[ResolutionStatus | None, Query(alias="status")] = None,
) -> list[ResolutionResponse]:
    stmt = select(CircularResolution).where(
        CircularResolution.organization_id == current_user.organization_id
    )
    if status_filter is not None:
        stmt = stmt.where(CircularResolution.status == status_filter)
    stmt = stmt.order_by(CircularResolution.closes_at.desc()).limit(200)
    rows = (await session.scalars(stmt)).all()
    return [_to_summary(r) for r in rows]


@admin_router.get("/{resolution_id}", response_model=ResolutionDetailResponse)
async def get_admin_resolution(
    resolution_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ResolutionDetailResponse:
    r = await session.scalar(
        select(CircularResolution).where(
            CircularResolution.id == resolution_id,
            CircularResolution.organization_id == current_user.organization_id,
        )
    )
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resolution not found")
    votes = list(
        (
            await session.scalars(
                select(CircularVote)
                .where(CircularVote.resolution_id == r.id)
                .order_by(CircularVote.voted_at)
            )
        ).all()
    )
    tally = await _tally(session, r)
    return _to_detail(
        r,
        votes,
        tally,
        my_impower_id=None,
        am_eligible=False,
        include_all_votes=True,
    )


@admin_router.post(
    "/{resolution_id}/close",
    response_model=ResolutionDetailResponse,
)
async def close_resolution(
    resolution_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
) -> ResolutionDetailResponse:
    """Close a resolution early + tally + render PDF + send result emails.

    Idempotent: if already decided (ANGENOMMEN/ABGELEHNT/GESCHLOSSEN), returns
    the current detail without re-running finalize. The Celery beat task calls
    the same `finalize_resolution` helper, so manual + scheduled close write
    identical state.
    """
    r = await session.scalar(
        select(CircularResolution).where(
            CircularResolution.id == resolution_id,
            CircularResolution.organization_id == current_user.organization_id,
        )
    )
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resolution not found")

    if r.status in (
        ResolutionStatus.ANGENOMMEN,
        ResolutionStatus.ABGELEHNT,
        ResolutionStatus.GESCHLOSSEN,
    ):
        votes = list(
            (
                await session.scalars(
                    select(CircularVote)
                    .where(CircularVote.resolution_id == r.id)
                    .order_by(CircularVote.voted_at)
                )
            ).all()
        )
        return _to_detail(
            r,
            votes,
            await _tally(session, r),
            my_impower_id=None,
            am_eligible=False,
            include_all_votes=True,
        )

    tally = await finalize_resolution(
        session,
        r,
        email_client,
        trigger="admin_manual",
        actor_user_id=current_user.id,
    )
    await session.commit()
    await session.refresh(r)

    votes = list(
        (
            await session.scalars(
                select(CircularVote)
                .where(CircularVote.resolution_id == r.id)
                .order_by(CircularVote.voted_at)
            )
        ).all()
    )
    return _to_detail(
        r,
        votes,
        tally,
        my_impower_id=None,
        am_eligible=False,
        include_all_votes=True,
    )


# --- PDF download endpoints --------------------------------------------------


@me_router.get("/{resolution_id}/result.pdf")
async def download_my_result_pdf(
    resolution_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    """Stream the protocol PDF to an eligible owner. 404 if not yet generated."""
    r = await _load_resolution_for_owner(session, current_user, resolution_id)
    if not r.result_pdf_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Protokoll noch nicht verfügbar."
        )
    path = resolve_result_pdf_path(r.id)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Protokoll noch nicht verfügbar."
        )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"Beschluss-{r.id.hex[:8]}.pdf",
    )


@admin_router.get("/{resolution_id}/result.pdf")
async def download_admin_result_pdf(
    resolution_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    r = await session.scalar(
        select(CircularResolution).where(
            CircularResolution.id == resolution_id,
            CircularResolution.organization_id == current_user.organization_id,
        )
    )
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resolution not found")
    path = resolve_result_pdf_path(r.id)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Protokoll noch nicht verfügbar."
        )
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"Beschluss-{r.id.hex[:8]}.pdf",
    )


# --- Public ballot endpoints (no auth — token is the credential) -------------


class BallotView(BaseModel):
    resolution_title: str
    description: str
    property_name: str
    mode: str
    closes_at: datetime
    status: str
    owner_name: str | None
    already_voted: bool
    open_for_voting: bool


class BallotVoteRequest(BaseModel):
    choice: VoteChoice


async def _load_ballot(
    session: AsyncSession, token: str
) -> tuple[ResolutionBallot, CircularResolution]:
    ballot = await session.scalar(select(ResolutionBallot).where(ResolutionBallot.token == token))
    if ballot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ungültiger oder abgelaufener Abstimmungslink.",
        )
    resolution = await session.get(CircularResolution, ballot.resolution_id)
    if resolution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Beschluss nicht gefunden."
        )
    return ballot, resolution


def _ballot_view(
    ballot: ResolutionBallot, resolution: CircularResolution, property_name: str
) -> BallotView:
    now = datetime.now(UTC)
    return BallotView(
        resolution_title=resolution.title,
        description=resolution.description,
        property_name=property_name,
        mode=resolution.mode.value,
        closes_at=resolution.closes_at,
        status=resolution.status.value,
        owner_name=ballot.owner_name,
        already_voted=ballot.voted_at is not None,
        open_for_voting=(
            resolution.status == ResolutionStatus.OFFEN and now < resolution.closes_at
        ),
    )


@public_router.get("/ballot/{token}", response_model=BallotView)
async def get_ballot(
    token: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BallotView:
    """Render one owner's ballot for the public voting page. No auth —
    the long random token is the credential and maps to exactly one
    resolution + one owner."""
    ballot, resolution = await _load_ballot(session, token)
    prop = await session.get(Property, resolution.property_id)
    return _ballot_view(ballot, resolution, prop.name if prop else "—")


@public_router.post(
    "/ballot/{token}/vote",
    response_model=BallotView,
    status_code=status.HTTP_201_CREATED,
)
async def cast_ballot_vote(
    token: str,
    req: BallotVoteRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BallotView:
    """Cast the owner's vote from the email link. One-shot: once this
    owner has voted (here OR via the portal), it's locked."""
    ballot, resolution = await _load_ballot(session, token)
    now = datetime.now(UTC)
    if resolution.status != ResolutionStatus.OFFEN or now >= resolution.closes_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Abstimmung ist nicht (mehr) offen.",
        )
    if ballot.voted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Sie haben bereits abgestimmt."
        )
    # One vote per owner across all channels: if a vote already exists
    # (e.g. cast in the portal), lock this ballot rather than duplicate.
    existing = await session.scalar(
        select(CircularVote).where(
            CircularVote.resolution_id == resolution.id,
            CircularVote.owner_contact_id_impower == ballot.owner_contact_id_impower,
        )
    )
    if existing is not None:
        ballot.voted_at = now
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Für diesen Eigentümer wurde bereits abgestimmt.",
        )

    client_host = request.client.host if request.client else ""
    ip_hash = hashlib.sha256((client_host + str(resolution.id)).encode("utf-8")).hexdigest()[:32]
    session.add(
        CircularVote(
            resolution_id=resolution.id,
            owner_contact_id_impower=ballot.owner_contact_id_impower,
            choice=req.choice,
            voter_user_id=None,
            signature_method="EMAIL_TOKEN",
            evidence_jsonb={
                "ip_hash": ip_hash,
                "user_agent": request.headers.get("user-agent", "")[:200],
                "ballot_id": str(ballot.id),
            },
        )
    )
    ballot.voted_at = now
    session.add(
        AuditLog(
            organization_id=resolution.organization_id,
            actor_user_id=None,
            action="resolution_voted_email",
            target_type="circular_resolutions",
            target_id=str(resolution.id),
            payload_json={
                "choice": req.choice.value,
                "owner_contact_id_impower": ballot.owner_contact_id_impower,
                "ballot_id": str(ballot.id),
            },
        )
    )
    await session.commit()
    prop = await session.get(Property, resolution.property_id)
    await session.refresh(ballot)
    return _ballot_view(ballot, resolution, prop.name if prop else "—")
