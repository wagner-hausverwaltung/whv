"""Post-meeting LLM extraction: read the signed Protokoll, merge
Beschluss outcomes + Diskussion into the existing agenda.

Distinct from invitation extraction (`etv_extraction.py`) because the
inputs and outputs differ:

  - Invitation: proposes meeting_date/location/agenda. We populate
    those fields on the assembly + create agenda items.
  - Protocol: confirms what actually happened. We MERGE into the
    existing agenda items (matched by `position`) rather than
    replace them, because the Verwalter may have edited the
    invitation-extracted items by hand and a wholesale replace
    would clobber that work. Per-TOP fields updated:
      * `beschluss_text` — meeting may amend the Vorschlag
      * `vote_yes` / `vote_no` / `vote_abstain` — Stimmen-counts
      * `vote_result` — ANGENOMMEN / ABGELEHNT
      * EtvDiscussionEntry rows — speaker + content per agenda item
    Plus on the assembly itself:
      * `actual_start`, `actual_end` — when the meeting actually ran
      * `status` → ABGEHALTEN (a signed protocol implies the meeting
        happened)

If the protocol introduces TOPs not present in the invitation
(unusual — "Sonstiges" items added in the meeting), we append them
with positions after the existing max.

Verified rows: same hard barrier as invitation extraction. Once a
Verwalter signs off, neither extractor touches the row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.llm import get_llm_provider
from app.integrations.llm.base import (
    LLMProvider,
    LLMProviderUnavailableError,
)
from app.models import (
    AgendaItemType,
    AgendaItemVoteResult,
    AssemblyStatus,
    EtvAgendaItem,
    EtvAssembly,
    EtvDiscussionEntry,
)
from app.services import llm_audit

# ---------------------------------------------------------------------------
# Pydantic schemas the LLM populates
# ---------------------------------------------------------------------------


class _ExtractedDiscussionEntry(BaseModel):
    """One Wortmeldung in the protocol's Diskussion section."""

    speaker_label: str = Field(
        description=(
            "Speaker identifier as printed in the protocol. Examples: "
            "'Herr Müller (Wohnung 4)', 'Verwalter', 'Beirat Frau Schmidt'. "
            "Preserve titles and parenthetical room references."
        ),
    )
    content: str = Field(
        description=(
            "Speaker's contribution, paraphrased if the protocol "
            "summarised it. Keep technical / legal terms verbatim."
        ),
    )


class _ExtractedProtocolAgendaItem(BaseModel):
    """One Tagesordnungspunkt as it actually played out."""

    position: int = Field(
        ge=1,
        description=(
            "TOP number as printed in the protocol. Used to match against "
            "the invitation-extracted agenda. If the protocol introduces "
            "a new TOP under 'Sonstiges' the model should still pick the "
            "printed position; service code handles appending."
        ),
    )
    title: str
    type: Literal["INFORMATION", "BESCHLUSS", "DISKUSSION"]
    final_beschluss_text: str | None = Field(
        default=None,
        description=(
            "For BESCHLUSS items only: the *final* wording voted on. "
            "May differ from the Beschlussvorschlag in the invitation "
            "(meetings often amend wording before voting). Null for "
            "INFORMATION/DISKUSSION."
        ),
    )
    vote_yes: int | None = Field(default=None, ge=0)
    vote_no: int | None = Field(default=None, ge=0)
    vote_abstain: int | None = Field(default=None, ge=0)
    vote_result: Literal["ANGENOMMEN", "ABGELEHNT"] | None = Field(
        default=None,
        description=(
            "Outcome as declared in the protocol. Null for INFORMATION/"
            "DISKUSSION items + for BESCHLUSS items the protocol didn't "
            "explicitly resolve."
        ),
    )
    discussion: list[_ExtractedDiscussionEntry] = Field(default_factory=list)


class ExtractedProtocol(BaseModel):
    """Top-level extraction result for a signed Protokoll."""

    actual_start: datetime | None = Field(
        default=None,
        description=(
            "When the meeting actually started, per the protocol header. "
            "ISO 8601 with Europe/Berlin tzinfo. Null if the protocol "
            "doesn't state it."
        ),
    )
    actual_end: datetime | None = Field(
        default=None,
        description="Actual meeting end, same caveats.",
    )
    quorum_reached: bool | None = Field(
        default=None,
        description=("Did the protocol declare the meeting beschlussfähig? Null if not stated."),
    )
    # NOTE: no `max_length=…` on any Field below — Gemini's
    # response_schema rejects JSON Schema's `maxLength`.
    attendance_summary: str | None = Field(
        default=None,
        description=(
            "Free-text snippet about who attended / MEA represented "
            "(e.g. '12 von 18 Eigentümern, 67% MEA'). Null if not "
            "summarised in the protocol."
        ),
    )
    agenda_outcomes: list[_ExtractedProtocolAgendaItem]


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


_PROMPT = """Sie sind Datenextraktionsspezialist für deutsche \
Wohnungseigentumsverwaltung (WEG-Recht).

Das angehängte PDF ist das *unterschriebene Protokoll* einer bereits \
*stattgefundenen* Eigentümerversammlung. Extrahieren Sie:

- actual_start / actual_end: Tatsächliche Beginn/Ende-Zeit der \
  Versammlung (im Protokollkopf, oft "Beginn der Versammlung: …"). \
  ISO 8601, Zeitzone Europe/Berlin. Null wenn nicht angegeben.

- quorum_reached: true wenn das Protokoll die Beschlussfähigkeit \
  feststellt, false wenn ausdrücklich nicht beschlussfähig, sonst null.

- attendance_summary: Kurze Zusammenfassung der Anwesenheit / \
  vertretenen Miteigentumsanteile (MEA). Beispiel: "14 von 18 \
  Eigentümern, 78% MEA vertreten". Null wenn nicht angegeben.

- agenda_outcomes: Alle behandelten Tagesordnungspunkte in der \
  Reihenfolge des Protokolls.
    * position: TOP-Nummer wie gedruckt (1, 2, 3, …). Falls die \
      Versammlung unter "Sonstiges" zusätzliche Punkte aufgenommen \
      hat, gibt die nächsthöhere Position zurück.
    * title: Überschrift des TOP, wie im Protokoll genannt.
    * type: BESCHLUSS, wenn ein Beschluss gefasst wurde (selbst wenn \
      er abgelehnt wurde). DISKUSSION, wenn ausdrücklich nur diskutiert \
      wurde. INFORMATION für reine Bekanntgaben.
    * final_beschluss_text: NUR bei type=BESCHLUSS — der wörtlich \
      abgestimmte Beschlusstext (das Protokoll zitiert ihn typischerweise \
      vor der Abstimmung). Falls die Versammlung die ursprüngliche \
      Formulierung geändert hat: die geänderte Fassung. Null sonst.
    * vote_yes / vote_no / vote_abstain: Stimmen-Anzahl (NICHT MEA). \
      Null wenn das Protokoll keine Tally nennt.
    * vote_result: "ANGENOMMEN" oder "ABGELEHNT" wie im Protokoll \
      festgestellt. Null bei INFORMATION/DISKUSSION.
    * discussion: Wortmeldungen pro TOP — speaker_label (z. B. \
      "Herr Müller (Wohnung 4)", "Verwalter", "Beirat Frau Schmidt") \
      und content (paraphrasiert wenn das Protokoll zusammenfasst, \
      sonst wörtlich). Leere Liste wenn das Protokoll keine \
      Diskussionspunkte zu diesem TOP nennt.

Geben Sie keine Felder zurück, die das Protokoll nicht ausdrücklich \
nennt. Lieber null als geraten."""


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------


async def extract_protocol_and_apply(
    session: AsyncSession,
    *,
    assembly_id: uuid.UUID,
    pdf_bytes: bytes,
    source_document_id: uuid.UUID | None,
    provider: LLMProvider | None = None,
) -> Literal["applied", "skipped_verified", "skipped_provider_unavailable"]:
    """Extract protocol details + merge into existing assembly.

    Merge semantics (vs. invitation extraction's replace):
      - Existing agenda items matched by `position` get their
        beschluss_text / vote_* / vote_result updated.
      - Items present in the invitation but absent from the protocol
        are left alone.
      - Items present in the protocol but absent from the invitation
        are appended with positions after the current max.
      - Discussion entries are wiped + re-created from the protocol
        per-item (the protocol IS the discussion record; the
        invitation has none).
    """
    if provider is None:
        provider = get_llm_provider()

    assembly = await session.get(EtvAssembly, assembly_id)
    if assembly is None:
        raise ValueError(f"Assembly not found: {assembly_id}")

    if assembly.verified_at is not None:
        await llm_audit.record(
            session,
            organization_id=assembly.organization_id,
            purpose="etv.extract_protocol",
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
            response_schema=ExtractedProtocol,
        )
    except LLMProviderUnavailableError as exc:
        await llm_audit.record(
            session,
            organization_id=assembly.organization_id,
            purpose="etv.extract_protocol",
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
            purpose="etv.extract_protocol",
            provider=provider.name,
            status=llm_audit.status_for_exception(exc),
            subject_kind="etv_assembly",
            subject_id=assembly_id,
            error=str(exc),
        )
        raise

    payload = result.payload

    # Apply scalar fields onto the assembly. A signed protocol is
    # conclusive evidence the meeting happened — status flips to
    # ABGEHALTEN unconditionally. The Verwalter can still override
    # via the manual edit form if they need ABGESAGT.
    if payload.actual_start:
        assembly.actual_start = _to_utc(payload.actual_start)
    if payload.actual_end:
        assembly.actual_end = _to_utc(payload.actual_end)
    if assembly.status != AssemblyStatus.ABGESAGT:
        assembly.status = AssemblyStatus.ABGEHALTEN

    assembly.protocol_extracted_at = datetime.now(UTC)
    assembly.protocol_extracted_source_document_id = source_document_id
    assembly.protocol_extracted_raw = payload.model_dump(mode="json")

    # Merge agenda items by position. Load existing into a dict.
    existing_items = (
        (
            await session.execute(
                select(EtvAgendaItem).where(EtvAgendaItem.assembly_id == assembly_id)
            )
        )
        .scalars()
        .all()
    )
    by_position: dict[int, EtvAgendaItem] = {i.position: i for i in existing_items}
    max_position = max((i.position for i in existing_items), default=0)

    # Wipe discussion across the whole assembly + re-create per the
    # protocol. The invitation extractor doesn't touch discussion, so
    # this is safe: protocol is the authoritative source of meeting
    # discussion content.
    if existing_items:
        await session.execute(
            delete(EtvDiscussionEntry).where(
                EtvDiscussionEntry.agenda_item_id.in_([i.id for i in existing_items])
            )
        )

    for outcome in payload.agenda_outcomes:
        item = by_position.get(outcome.position)
        if item is None:
            # New TOP introduced in the meeting itself ("Sonstiges").
            # Append after the current max.
            max_position += 1
            item = EtvAgendaItem(
                assembly_id=assembly_id,
                position=max_position,
                type=AgendaItemType(outcome.type),
                title=outcome.title,
                body="",
                beschluss_text=outcome.final_beschluss_text,
            )
            session.add(item)
            await session.flush()
            by_position[max_position] = item
        else:
            # Update the existing row's fields. Title is overwritten
            # because the protocol's title is more accurate (the
            # invitation's was a proposal). Body is left alone — that
            # was the Verwalter's narrative pre-meeting.
            item.title = outcome.title
            if outcome.final_beschluss_text is not None:
                item.beschluss_text = outcome.final_beschluss_text

        # Vote tallies — explicit None means "protocol didn't say,
        # leave existing value alone". Zero means "protocol said
        # zero", which we accept.
        if outcome.vote_yes is not None:
            item.vote_yes = outcome.vote_yes
        if outcome.vote_no is not None:
            item.vote_no = outcome.vote_no
        if outcome.vote_abstain is not None:
            item.vote_abstain = outcome.vote_abstain
        if outcome.vote_result is not None:
            item.vote_result = AgendaItemVoteResult(outcome.vote_result)

        # Discussion entries — already wiped above; insert fresh.
        for idx, entry in enumerate(outcome.discussion, start=1):
            session.add(
                EtvDiscussionEntry(
                    agenda_item_id=item.id,
                    position=idx,
                    speaker_label=entry.speaker_label,
                    content=entry.content,
                )
            )

    await llm_audit.record(
        session,
        organization_id=assembly.organization_id,
        purpose="etv.extract_protocol",
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
