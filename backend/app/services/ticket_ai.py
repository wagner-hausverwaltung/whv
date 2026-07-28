"""KI-Antwortentwurf für Eigentümer-Tickets.

Ein neues Ticket von einem Eigentümer/Mieter löst (Celery, best-effort)
einen Entwurf aus: die RAG-Pipeline läuft MIT DEN SICHTRECHTEN DES
FRAGESTELLERS (ihre Dokumente + Stammdaten-Karten + der öffentliche
Gesetzes-Korpus) und das Ergebnis landet als Verwalter-only INTERNE NOTIZ
am Ticket — nie direkt beim Eigentümer. Der Verwalter prüft, editiert und
sendet über den bestehenden Ticket-Antwortweg.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Ticket, TicketMessage, User, UserRole
from app.rag.generation import AssistantAnswer, answer_question
from app.rag.ingestion import Embedder

logger = logging.getLogger(__name__)

DRAFT_MARKER = "🤖 KI-Entwurf"

_DISCLAIMER = (
    "Hinweis für den Verwalter: Entwurf automatisch erstellt — vor dem Senden "
    "prüfen. Rechtliche Aussagen sind keine Rechtsberatung."
)

# Cap how much ticket text goes into the question — support mails can carry
# quoted history chains; the first message body is what matters.
_MAX_QUESTION_CHARS = 4000


async def resolve_draft_user(session: AsyncSession, ticket: Ticket) -> User | None:
    """The user whose visibility scope grounds the draft: the ticket creator,
    or (email tickets) the registered user behind the sender address. None →
    unknown external sender or a Verwalter's own ticket → no draft."""
    user: User | None = None
    if ticket.created_by_user_id is not None:
        user = await session.get(User, ticket.created_by_user_id)
    elif ticket.external_sender_email:
        user = await session.scalar(
            select(User).where(
                User.email == ticket.external_sender_email.lower(),
                User.deleted_at.is_(None),
            )
        )
    if user is None or user.deleted_at is not None or user.role == UserRole.VERWALTER:
        return None
    return user


def compose_question(subject: str, bodies: list[str]) -> str:
    """Frame the ticket as a question for the grounded answer pipeline."""
    text = "\n\n".join(b.strip() for b in bodies if b.strip())[:_MAX_QUESTION_CHARS]
    return (
        "Ein Eigentümer/Mieter hat folgende Support-Anfrage gestellt. "
        "Beantworte sie sachlich und freundlich als Entwurf für die "
        f"Hausverwaltung.\n\nBetreff: {subject}\n\n{text}"
    )


def build_draft_body(answer: AssistantAnswer) -> str:
    """Render the internal-note body: marker, answer, sources, disclaimer."""
    lines = [DRAFT_MARKER, "", answer.answer.strip()]
    if answer.sources:
        lines += ["", "Quellen:"]
        for c in answer.sources:
            label = c.source_kind or "Dokument"
            if c.contact_name:
                label += f" · {c.contact_name}"
            if c.page is not None:
                label += f" · S. {c.page}"
            lines.append(f"  [{c.index}] {label}")
    lines += ["", _DISCLAIMER]
    return "\n".join(lines)


async def generate_ticket_draft(
    app_session: AsyncSession,
    rag_session: AsyncSession,
    *,
    ticket_id: uuid.UUID,
    settings: Settings,
    embedder: Embedder,
    generator: object,
) -> str:
    """Create the draft note for one ticket. Idempotent: an existing draft
    note short-circuits. Returns a short status string for task logs."""
    ticket = await app_session.get(Ticket, ticket_id)
    if ticket is None:
        return "no_ticket"

    existing = await app_session.scalar(
        select(TicketMessage.id).where(
            TicketMessage.ticket_id == ticket.id,
            TicketMessage.is_internal_note.is_(True),
            TicketMessage.body.like(f"{DRAFT_MARKER}%"),
        )
    )
    if existing is not None:
        return "exists"

    user = await resolve_draft_user(app_session, ticket)
    if user is None:
        return "no_user"

    bodies = (
        await app_session.scalars(
            select(TicketMessage.body)
            .where(
                TicketMessage.ticket_id == ticket.id,
                TicketMessage.is_internal_note.is_(False),
            )
            .order_by(TicketMessage.created_at)
            .limit(3)
        )
    ).all()
    question = compose_question(ticket.subject, list(bodies))

    answer = await answer_question(
        app_session,
        rag_session,
        user=user,
        question=question,
        embedder=embedder,
        generator=generator,  # type: ignore[arg-type]
        settings=settings,
        property_id=ticket.property_id,
    )

    app_session.add(
        TicketMessage(
            ticket_id=ticket.id,
            author_user_id=None,
            body=build_draft_body(answer),
            is_internal_note=True,
        )
    )
    await app_session.commit()
    return "abstained" if answer.abstained else "drafted"
