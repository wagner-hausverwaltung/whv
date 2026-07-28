"""KI-Antwortentwurf für Tickets: Nutzer-Auflösung, Frage-Komposition und
Notiz-Rendering (der volle RAG-Lauf braucht den Store und läuft in CI)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.models import Organization, Ticket, TicketCategory, TicketStatus, UserRole
from app.rag.generation import AssistantAnswer, Citation
from app.rag.masterdata import law_doc_id
from app.services.ticket_ai import (
    DRAFT_MARKER,
    build_draft_body,
    compose_question,
    resolve_draft_user,
)
from app.tests._factories import make_org, make_user


async def _make_ticket(engine: AsyncEngine, org: Organization, **kwargs: object) -> Ticket:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        t = Ticket(
            organization_id=org.id,
            category=TicketCategory.SONSTIGES_OTHER,
            status=TicketStatus.NEU,
            subject=kwargs.pop("subject", "Frage zur Abrechnung"),
            **kwargs,
        )
        s.add(t)
        await s.commit()
        await s.refresh(t)
    return t


async def test_resolve_draft_user_owner_and_verwalter(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    owner, _, _ = await make_user(test_engine, org=org, role=UserRole.EIGENTUEMER)
    verwalter, _, _ = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    t_owner = await _make_ticket(test_engine, org, created_by_user_id=owner.id)
    t_verw = await _make_ticket(test_engine, org, created_by_user_id=verwalter.id)

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        resolved = await resolve_draft_user(s, t_owner)
        assert resolved is not None and resolved.id == owner.id
        assert await resolve_draft_user(s, t_verw) is None


async def test_resolve_draft_user_external_email(test_engine: AsyncEngine) -> None:
    org = await make_org(test_engine)
    owner, email, _ = await make_user(test_engine, org=org, role=UserRole.MIETER)
    t_known = await _make_ticket(test_engine, org, external_sender_email=email)
    t_unknown = await _make_ticket(test_engine, org, external_sender_email="fremd@example.org")

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        resolved = await resolve_draft_user(s, t_known)
        assert resolved is not None and resolved.id == owner.id
        assert await resolve_draft_user(s, t_unknown) is None


def test_compose_question_truncates() -> None:
    q = compose_question("Betreffzeile", ["A" * 10_000])
    assert "Betreffzeile" in q
    assert len(q) < 5_000


def test_build_draft_body_marker_sources_disclaimer() -> None:
    org_id = uuid.uuid4()
    answer = AssistantAnswer(
        answer="Die Jahresabrechnung ist gemäß § 28 WEG zu beschließen [1].",
        abstained=False,
        sources=[
            Citation(
                index=1,
                document_id=law_doc_id(org_id, "WEG", "§ 28"),
                page=None,
                source_kind="GESETZ",
                contact_name=None,
                source_type="law",
            )
        ],
        retrieved_document_ids=[],
    )
    body = build_draft_body(answer)
    assert body.startswith(DRAFT_MARKER)
    assert "§ 28 WEG" in body
    assert "[1] GESETZ" in body
    assert "keine Rechtsberatung" in body
