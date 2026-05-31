"""VERWALTER-only overview of assistant conversations (ADR-0013).

Reads the `assistant_messages` log: a paginated list grouped into threads by
`conversation_id`, plus a per-thread detail with each turn's question, answer,
cited documents (resolved to names), and the property the search was scoped
to. Org-scoped + VERWALTER-only — it exposes users' Q&A over their own data.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.db import get_session
from app.models import AssistantMessage, Document, Property, User
from app.models.user import UserRole

router = APIRouter(prefix="/admin/assistant", tags=["admin-assistant"])

_verwalter_only = require_role(UserRole.VERWALTER)


class ConversationSummary(BaseModel):
    conversation_id: uuid.UUID
    user_email: str | None
    property_id: uuid.UUID | None
    property_name: str | None
    started_at: datetime
    last_at: datetime
    message_count: int
    first_question: str


class ConversationListResponse(BaseModel):
    items: list[ConversationSummary]


class CitationOut(BaseModel):
    index: int | None = None
    document_id: str | None = None
    document_name: str | None = None
    page: int | None = None
    source_kind: str | None = None
    source_type: str | None = None
    contact_name: str | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    question: str
    answer: str
    abstained: bool
    property_id: uuid.UUID | None
    citations: list[CitationOut]
    created_at: datetime


class ConversationDetailResponse(BaseModel):
    conversation_id: uuid.UUID
    user_email: str | None
    property_name: str | None
    messages: list[MessageOut]


async def _resolve_property_names(
    session: AsyncSession, ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = (await session.scalars(select(Property).where(Property.id.in_(ids)))).all()
    return {p.id: p.name for p in rows}


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    user_id: uuid.UUID | None = None,
    property_id: uuid.UUID | None = None,
) -> ConversationListResponse:
    org = current_user.organization_id
    where = [AssistantMessage.organization_id == org]
    if user_id is not None:
        where.append(AssistantMessage.actor_user_id == user_id)
    if property_id is not None:
        where.append(AssistantMessage.property_id == property_id)

    agg = (
        select(
            AssistantMessage.conversation_id.label("cid"),
            func.min(AssistantMessage.created_at).label("started"),
            func.max(AssistantMessage.created_at).label("last"),
            func.count().label("cnt"),
        )
        .where(*where)
        .group_by(AssistantMessage.conversation_id)
        .order_by(func.max(AssistantMessage.created_at).desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(agg)).all()
    cids = [r.cid for r in rows]
    if not cids:
        return ConversationListResponse(items=[])

    # Earliest message per conversation → first question + originating user/prop.
    msgs = (
        (
            await session.execute(
                select(AssistantMessage)
                .where(AssistantMessage.conversation_id.in_(cids))
                .order_by(AssistantMessage.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    first_by_cid: dict[uuid.UUID, AssistantMessage] = {}
    for m in msgs:
        first_by_cid.setdefault(m.conversation_id, m)

    user_ids = {m.actor_user_id for m in first_by_cid.values() if m.actor_user_id is not None}
    users: dict[uuid.UUID, str] = {}
    if user_ids:
        users = {
            u.id: u.email
            for u in (await session.scalars(select(User).where(User.id.in_(user_ids)))).all()
        }
    props = await _resolve_property_names(
        session, {m.property_id for m in first_by_cid.values() if m.property_id is not None}
    )

    items: list[ConversationSummary] = []
    for r in rows:
        first = first_by_cid.get(r.cid)
        items.append(
            ConversationSummary(
                conversation_id=r.cid,
                user_email=users.get(first.actor_user_id)
                if (first and first.actor_user_id)
                else None,
                property_id=first.property_id if first else None,
                property_name=props.get(first.property_id)
                if (first and first.property_id)
                else None,
                started_at=r.started,
                last_at=r.last,
                message_count=r.cnt,
                first_question=first.question if first else "",
            )
        )
    return ConversationListResponse(items=items)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: Annotated[User, Depends(_verwalter_only)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ConversationDetailResponse:
    org = current_user.organization_id
    msgs = (
        (
            await session.execute(
                select(AssistantMessage)
                .where(
                    AssistantMessage.organization_id == org,
                    AssistantMessage.conversation_id == conversation_id,
                )
                .order_by(AssistantMessage.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not msgs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Konversation nicht gefunden")

    user = await session.get(User, msgs[0].actor_user_id) if msgs[0].actor_user_id else None
    props = await _resolve_property_names(
        session, {m.property_id for m in msgs if m.property_id is not None}
    )

    # Resolve real document names for citations (master-data synthetic ids
    # simply won't match a Document → name stays None, label falls back).
    doc_ids: set[uuid.UUID] = set()
    for m in msgs:
        for c in m.citations or []:
            raw = c.get("document_id")
            if isinstance(raw, str):
                try:
                    doc_ids.add(uuid.UUID(raw))
                except ValueError:
                    continue
    doc_names: dict[uuid.UUID, str] = {}
    if doc_ids:
        doc_names = {
            d.id: d.name
            for d in (await session.scalars(select(Document).where(Document.id.in_(doc_ids)))).all()
        }

    def _citation_out(c: dict[str, Any]) -> CitationOut:
        raw = c.get("document_id")
        name: str | None = None
        if isinstance(raw, str):
            try:
                name = doc_names.get(uuid.UUID(raw))
            except ValueError:
                name = None
        return CitationOut(
            index=c.get("index"),
            document_id=raw if isinstance(raw, str) else None,
            document_name=name,
            page=c.get("page"),
            source_kind=c.get("source_kind"),
            source_type=c.get("source_type"),
            contact_name=c.get("contact_name"),
        )

    first_prop = next((m.property_id for m in msgs if m.property_id is not None), None)
    return ConversationDetailResponse(
        conversation_id=conversation_id,
        user_email=user.email if user else None,
        property_name=props.get(first_prop) if first_prop else None,
        messages=[
            MessageOut(
                id=m.id,
                question=m.question,
                answer=m.answer,
                abstained=m.abstained,
                property_id=m.property_id,
                citations=[_citation_out(c) for c in (m.citations or [])],
                created_at=m.created_at,
            )
            for m in msgs
        ],
    )
