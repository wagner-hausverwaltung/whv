"""LLM-driven extraction of Eigentümerversammlung details from
invitation PDFs (ADR-0008).

The Celery task wraps this helper. Keeping the helper Celery-free
means we can unit-test it with a mocked provider + an in-memory
session — no broker, no real API calls, no flaky CI.

Idempotency model:
- If `verified_at` is set on the assembly, this function is a no-op
  (the Verwalter signed off — never overwrite their work).
- Otherwise extraction runs, overwrites scheduled_start / end /
  location, stamps `auto_extracted_at`, and replaces ALL existing
  agenda items with the new extraction. (We don't try to merge:
  position numbers change between extractions and merging produces
  worse data than just re-doing it.)

The prompt is in German because the source documents are. Switching
to multilingual would mean re-evaluating against German invitations
before shipping.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.llm import get_llm_provider
from app.integrations.llm.base import (
    LLMProvider,
    LLMProviderUnavailable,
)
from app.models import (
    AgendaItemType,
    EtvAgendaItem,
    EtvAssembly,
)
from app.services import llm_audit

# ---------------------------------------------------------------------------
# Pydantic schemas the LLM must populate
# ---------------------------------------------------------------------------


class _ExtractedAgendaItem(BaseModel):
    """One Tagesordnungspunkt as parsed from the invitation."""

    position: int = Field(
        ge=1,
        description="Sequence number (1, 2, 3, …) as printed on the invitation.",
    )
    type: Literal["INFORMATION", "BESCHLUSS", "DISKUSSION"] = Field(
        description=(
            "Kind of agenda item — INFORMATION for announcements, "
            "BESCHLUSS for items requiring a vote, DISKUSSION for items "
            "explicitly listed as discussion without a vote."
        ),
    )
    title: str = Field(
        max_length=500,
        description="The TOP heading verbatim from the invitation.",
    )
    body: str | None = Field(
        default=None,
        description=(
            "Explanatory paragraph beneath the heading if present. "
            "Null if the invitation has no such paragraph for this TOP."
        ),
    )
    beschluss_text: str | None = Field(
        default=None,
        description=(
            "For type=BESCHLUSS only: the exact Beschlussvorschlag text "
            "the meeting will vote on. Null for INFORMATION / DISKUSSION."
        ),
    )


class ExtractedAssembly(BaseModel):
    """Top-level extraction result."""

    meeting_date: datetime = Field(
        description=(
            "The actual meeting start (NOT the invitation/letter date). "
            "ISO 8601 with Europe/Berlin timezone."
        )
    )
    meeting_end: datetime = Field(
        description=(
            "Meeting end timestamp. If not stated, set to meeting_date "
            "+ 3 hours."
        )
    )
    location: str = Field(
        max_length=500,
        description=(
            "Where the meeting takes place. Full address or named room "
            "(e.g. 'Vereinsheim, Hasenbergstr. 32, 70176 Stuttgart')."
        ),
    )
    agenda_items: list[_ExtractedAgendaItem] = Field(
        description="Tagesordnungspunkte in printed order.",
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_PROMPT = """Sie sind ein Datenextraktionsspezialist für deutsche \
Wohnungseigentumsverwaltung (WEG-Recht).

Das angehängte PDF ist eine Einladung zu einer Eigentümerversammlung. \
Extrahieren Sie die folgenden Felder als JSON gemäß dem vorgegebenen \
Schema:

- meeting_date: Datum und Uhrzeit, an dem die VERSAMMLUNG STATTFINDET. \
  Das ist NICHT das Datum oben auf dem Brief (Briefdatum / Schreiben \
  vom …), sondern das Datum im Einladungstext ("hiermit lade ich Sie \
  zur ordentlichen Eigentümerversammlung am … um … Uhr ein"). \
  ISO 8601, Zeitzone Europe/Berlin. \
  Falls keine Uhrzeit angegeben ist, verwenden Sie 18:00.

- meeting_end: Ende der Versammlung. Wenn nicht ausdrücklich genannt: \
  meeting_date + 3 Stunden.

- location: Vollständiger Versammlungsort (Räumlichkeit + Adresse).

- agenda_items: Alle Tagesordnungspunkte in der gedruckten Reihenfolge. \
  position startet bei 1. type ist:
    * "BESCHLUSS"     wenn der TOP einen Beschlussvorschlag enthält \
                      (typisch: "Beschlussvorschlag:", "Die \
                      Eigentümergemeinschaft beschließt …").
    * "DISKUSSION"    wenn der TOP ausdrücklich nur eine Aussprache \
                      vorsieht ("Aussprache zu …", "Besprechung über …").
    * "INFORMATION"   sonst (Begrüßung, Anwesenheit, Bekanntmachungen, \
                      Verschiedenes ohne Abstimmung, Sonstiges).

beschluss_text ist NUR bei type=BESCHLUSS gefüllt — der wörtliche \
Beschlussvorschlag, ohne Kommentar oder Begründung.

Geben Sie keine Felder zurück, die im PDF nicht ausdrücklich stehen. \
Lieber null als geraten."""


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------


async def extract_and_apply(
    session: AsyncSession,
    *,
    assembly_id: uuid.UUID,
    pdf_bytes: bytes,
    source_document_id: uuid.UUID | None,
    provider: LLMProvider | None = None,
) -> Literal["applied", "skipped_verified", "skipped_provider_unavailable"]:
    """Extract assembly details from a PDF and write them onto the row.

    Returns a coarse outcome string for the Celery task to log. Caller
    commits — we don't take the session out from under them.

    The provider is injectable for tests; in production code path the
    default `get_llm_provider()` factory is used.
    """
    if provider is None:
        provider = get_llm_provider()

    assembly = await session.get(EtvAssembly, assembly_id)
    if assembly is None:
        raise ValueError(f"Assembly not found: {assembly_id}")

    if assembly.verified_at is not None:
        # Verwalter has already curated this row. The LLM's output
        # would only undo their work. Audit log notes the no-op.
        await llm_audit.record(
            session,
            organization_id=assembly.organization_id,
            purpose="etv.extract_metadata",
            provider=provider.name,
            status="ok",
            subject_kind="etv_assembly",
            subject_id=assembly_id,
            error="skipped: assembly already verified",
        )
        return "skipped_verified"

    try:
        result = await provider.extract_from_pdf(
            pdf_bytes=pdf_bytes,
            prompt=_PROMPT,
            response_schema=ExtractedAssembly,
        )
    except LLMProviderUnavailable as exc:
        await llm_audit.record(
            session,
            organization_id=assembly.organization_id,
            purpose="etv.extract_metadata",
            provider=provider.name,
            status=llm_audit.status_for_exception(exc),
            subject_kind="etv_assembly",
            subject_id=assembly_id,
            error=str(exc),
        )
        return "skipped_provider_unavailable"
    except Exception as exc:
        await llm_audit.record(
            session,
            organization_id=assembly.organization_id,
            purpose="etv.extract_metadata",
            provider=provider.name,
            status=llm_audit.status_for_exception(exc),
            subject_kind="etv_assembly",
            subject_id=assembly_id,
            error=str(exc),
        )
        raise

    payload = result.payload

    # Coerce to UTC at write-time so the DB stores tz-aware UTC like
    # every other timestamp in the schema. Gemini gives us Europe/
    # Berlin per the prompt; if it ever forgets the tzinfo we treat
    # the value as already-UTC rather than guessing.
    assembly.scheduled_start = _to_utc(payload.meeting_date)
    assembly.scheduled_end = _to_utc(payload.meeting_end)
    assembly.location = payload.location
    assembly.auto_extracted_at = datetime.now(UTC)
    assembly.auto_extracted_source_document_id = source_document_id
    assembly.auto_extracted_raw = payload.model_dump(mode="json")

    # Wipe existing agenda items (we proved above that verified_at is
    # null, so the Verwalter hasn't curated these). CASCADE on the FK
    # also removes attached discussion entries — fine for the auto-
    # extracted path because we don't extract discussion from the
    # invitation; discussion is only filled post-meeting.
    await session.execute(
        delete(EtvAgendaItem).where(EtvAgendaItem.assembly_id == assembly_id)
    )
    for idx, item in enumerate(payload.agenda_items, start=1):
        position = item.position if item.position >= 1 else idx
        session.add(
            EtvAgendaItem(
                assembly_id=assembly_id,
                position=position,
                type=AgendaItemType(item.type),
                title=item.title,
                body=item.body or "",
                beschluss_text=item.beschluss_text,
            )
        )

    await llm_audit.record(
        session,
        organization_id=assembly.organization_id,
        purpose="etv.extract_metadata",
        provider=provider.name,
        status="ok",
        stats=result.stats,
        subject_kind="etv_assembly",
        subject_id=assembly_id,
    )
    return "applied"


def _to_utc(dt: datetime) -> datetime:
    """Normalize a tz-aware (or naive) datetime to UTC for storage."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
