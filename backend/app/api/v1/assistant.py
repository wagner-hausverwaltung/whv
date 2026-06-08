"""RAG assistant endpoint (ADR-0013) — POST /assistant/query.

The backend is the only gateway: it authenticates the caller, resolves
their ACL scope, retrieves only permitted chunks, and asks Gemini to answer
with required citations (or abstain). Ships dark behind `rag_enabled`.
Citations are ACL-gated by construction — they carry a document id the SPA
opens via the existing auth-gated download endpoint, which re-checks access.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.integrations.llm import get_llm_provider
from app.models import AssistantMessage, AuditLog, User
from app.rag.db import rag_session_scope
from app.rag.generation import ConversationTurn, answer_question
from app.ratelimit import rate_limit

router = APIRouter(prefix="/assistant", tags=["assistant"])


class ConversationTurnRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AssistantQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    # Recent chat turns for multi-turn follow-ups (oldest→newest). Capped so the
    # prompt stays bounded; the generation layer also trims to the last few.
    history: list[ConversationTurnRequest] = Field(default_factory=list, max_length=20)
    # The property selected in the UI's switcher — scopes retrieval to that
    # property's documents/cards only. None = the caller's whole visible scope.
    property_id: uuid.UUID | None = None
    # Per-chat-session id (client-minted) — groups turns into one conversation
    # in the VERWALTER overview. None → a fresh id per query (standalone turn).
    conversation_id: uuid.UUID | None = None
    # Optional structured filters (the "hybrid" half) — the SPA can pass these
    # from UI facets; free-text questions work without them.
    issued_year: int | None = None
    kind: str | None = None
    contact: str | None = None
    # UI language ("de"/"en") so the answer + abstain phrase come back in the
    # user's language. None → the model mirrors the question's own language.
    language: str | None = Field(default=None, max_length=8)


class CitationResponse(BaseModel):
    # The [index] the answer cited — the SPA labels the chip "[index] …" so the
    # inline marker maps to a clickable source.
    index: int
    document_id: uuid.UUID
    page: int | None
    source_kind: str | None
    contact_name: str | None
    # "document" (open via /me/documents/{id}/file) vs a master-data card like
    # "dienstleister" (the client deep-links to the entity using contact_id +
    # property_id instead of downloading a file). ADR-0013 §4.
    source_type: str = "document"
    contact_id: uuid.UUID | None = None
    property_id: uuid.UUID | None = None


class AssistantQueryResponse(BaseModel):
    answer: str
    abstained: bool
    sources: list[CitationResponse]


@router.post(
    "/query",
    response_model=AssistantQueryResponse,
    dependencies=[Depends(rate_limit("assistant_query", limit=30, window_seconds=300))],
)
async def assistant_query(
    body: AssistantQueryRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    app_session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AssistantQueryResponse:
    if not settings.rag_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Der Assistent ist derzeit nicht verfügbar.",
        )

    provider = get_llm_provider()
    async with rag_session_scope() as rag_session:
        answer = await answer_question(
            app_session,
            rag_session,
            user=current_user,
            question=body.question,
            embedder=provider,
            generator=provider,
            settings=settings,
            history=[ConversationTurn(role=t.role, content=t.content) for t in body.history],
            property_id=body.property_id,
            issued_year=body.issued_year,
            kind=body.kind,
            contact_query=body.contact,
            language=body.language,
        )

    # Query audit log — DSGVO accountability + a source for the eval set.
    app_session.add(
        AuditLog(
            organization_id=current_user.organization_id,
            actor_user_id=current_user.id,
            action="assistant_query",
            target_type="assistant",
            target_id=None,
            payload_json={
                "question": body.question,
                "abstained": answer.abstained,
                "retrieved_document_ids": [str(d) for d in answer.retrieved_document_ids],
            },
        )
    )
    # Full Q&A turn for the VERWALTER conversation overview. conversation_id
    # groups turns into a thread; a missing one (older client) → standalone.
    app_session.add(
        AssistantMessage(
            organization_id=current_user.organization_id,
            conversation_id=body.conversation_id or uuid.uuid4(),
            actor_user_id=current_user.id,
            property_id=body.property_id,
            question=body.question,
            answer=answer.answer,
            abstained=answer.abstained,
            citations=[
                {
                    "index": c.index,
                    "document_id": str(c.document_id),
                    "page": c.page,
                    "source_kind": c.source_kind,
                    "source_type": c.source_type,
                    "contact_name": c.contact_name,
                }
                for c in answer.sources
            ],
            retrieved_document_ids=[str(d) for d in answer.retrieved_document_ids],
        )
    )
    await app_session.commit()

    return AssistantQueryResponse(
        answer=answer.answer,
        abstained=answer.abstained,
        sources=[
            CitationResponse(
                index=citation.index,
                document_id=citation.document_id,
                page=citation.page,
                source_kind=citation.source_kind,
                contact_name=citation.contact_name,
                # Propagate the master-data signals — without these the
                # response defaulted source_type to "document", so the SPA
                # tried to download a card's synthetic id as a PDF (404).
                source_type=citation.source_type,
                contact_id=citation.contact_id,
                property_id=citation.property_id,
            )
            for citation in answer.sources
        ],
    )
