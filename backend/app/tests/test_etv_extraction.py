"""Tests for `extract_and_apply` — the provider-agnostic helper that
writes LLM output onto an assembly.

We mock the provider rather than the SDK so the tests don't depend
on the Gemini protobuf wheels. The mock implements `LLMProvider`
faithfully (name, extract_from_pdf signature) so type-level mistakes
in the service surface here, not in production.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.integrations.llm.base import (
    LLMCallStats,
    LLMParseError,
    LLMProviderUnavailableError,
    LLMResult,
)
from app.models import (
    AgendaItemType,
    AssemblyStatus,
    EtvAgendaItem,
    EtvAssembly,
    LLMAuditLog,
    UserRole,
)
from app.services.etv_extraction import (
    ExtractedAssembly,
    extract_and_apply,
)
from app.tests._factories import make_org, make_property, make_user

# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------


class _MockProvider:
    name = "mock"

    def __init__(self, payload: ExtractedAssembly, *, raise_with: Exception | None = None):
        self._payload = payload
        self._raise = raise_with

    async def extract_from_pdf(
        self,
        *,
        pdf_bytes: bytes,
        prompt: str,
        response_schema: type[ExtractedAssembly],
    ) -> LLMResult[ExtractedAssembly]:
        if self._raise is not None:
            raise self._raise
        return LLMResult(
            payload=self._payload,
            stats=LLMCallStats(
                model="mock-flash", input_tokens=4321, output_tokens=987, latency_ms=120
            ),
        )


def _make_payload(*, agenda_count: int = 3, with_beschluss: bool = True) -> ExtractedAssembly:
    items = []
    for i in range(1, agenda_count + 1):
        items.append(
            {
                "position": i,
                "type": ("BESCHLUSS" if (with_beschluss and i == 2) else "INFORMATION"),
                "title": f"TOP {i}",
                "body": f"Erläuterung {i}",
                "beschluss_text": (
                    "Die Eigentümergemeinschaft beschließt …" if with_beschluss and i == 2 else None
                ),
            }
        )
    return ExtractedAssembly.model_validate(
        {
            "meeting_date": "2026-04-25T18:00:00+02:00",
            "meeting_end": "2026-04-25T21:00:00+02:00",
            "location": "Vereinsheim, Hasenbergstr. 32, 70176 Stuttgart",
            "agenda_items": items,
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_apply_writes_assembly_fields_and_agenda(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    # Seed a stub the way the backfill service would.
    async with sm() as s:
        stub = EtvAssembly(
            organization_id=org.id,
            property_id=prop.id,
            title="Eigentümerversammlung 2026",
            description="Automatisch aus Bestand übernommen.",
            location="(noch nicht erfasst)",
            scheduled_start=datetime(2026, 4, 2, 16, 0, tzinfo=UTC),
            scheduled_end=datetime(2026, 4, 2, 19, 0, tzinfo=UTC),
            status=AssemblyStatus.EINGELADEN,
        )
        s.add(stub)
        await s.commit()
        stub_id = stub.id

    provider = _MockProvider(_make_payload(agenda_count=3))

    async with sm() as s:
        outcome = await extract_and_apply(
            s,
            assembly_id=stub_id,
            pdf_bytes=b"%PDF-fake",
            source_document_id=None,
            provider=provider,  # type: ignore[arg-type]
        )
        await s.commit()
    assert outcome == "applied"

    async with sm() as s:
        row = await s.get(EtvAssembly, stub_id)
        assert row is not None
        # Date moved from the placeholder (2026-04-02) to the
        # extracted meeting_date (2026-04-25).
        assert row.scheduled_start.date().isoformat() == "2026-04-25"
        assert row.location.startswith("Vereinsheim")
        assert row.auto_extracted_at is not None
        assert row.auto_extracted_raw is not None
        assert row.verified_at is None  # extraction != verification

        agenda = (
            (
                await s.execute(
                    select(EtvAgendaItem)
                    .where(EtvAgendaItem.assembly_id == stub_id)
                    .order_by(EtvAgendaItem.position)
                )
            )
            .scalars()
            .all()
        )
    assert [a.position for a in agenda] == [1, 2, 3]
    assert agenda[1].type == AgendaItemType.BESCHLUSS
    assert agenda[1].beschluss_text and agenda[1].beschluss_text.startswith(
        "Die Eigentümergemeinschaft"
    )
    # INFORMATION rows must have null beschluss_text — sanity check
    # the prompt's instruction was honored.
    assert agenda[0].beschluss_text is None


async def test_apply_is_noop_when_verified(test_engine: AsyncEngine) -> None:
    """Once a Verwalter signs off (`verified_at` set), the LLM must
    not overwrite their work — even if extraction would otherwise
    succeed."""
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    user, _, _ = await make_user(test_engine, org=org, role=UserRole.VERWALTER)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    async with sm() as s:
        stub = EtvAssembly(
            organization_id=org.id,
            property_id=prop.id,
            title="Eigentümerversammlung 2026",
            description="...",
            location="Bereits geprüft",
            scheduled_start=datetime(2026, 4, 25, 16, 0, tzinfo=UTC),
            scheduled_end=datetime(2026, 4, 25, 19, 0, tzinfo=UTC),
            status=AssemblyStatus.ABGEHALTEN,
            verified_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
            verified_by_user_id=user.id,
        )
        s.add(stub)
        await s.commit()
        stub_id = stub.id

    # Would otherwise mutate the row.
    provider = _MockProvider(_make_payload())

    async with sm() as s:
        outcome = await extract_and_apply(
            s,
            assembly_id=stub_id,
            pdf_bytes=b"%PDF-fake",
            source_document_id=None,
            provider=provider,  # type: ignore[arg-type]
        )
        await s.commit()
    assert outcome == "skipped_verified"

    async with sm() as s:
        row = await s.get(EtvAssembly, stub_id)
        assert row is not None
        # Location untouched.
        assert row.location == "Bereits geprüft"
        # No agenda items created.
        n = (
            await s.execute(select(EtvAgendaItem).where(EtvAgendaItem.assembly_id == stub_id))
        ).all()
        assert n == []
        # Audit row still logged the no-op.
        audit = (
            (await s.execute(select(LLMAuditLog).where(LLMAuditLog.subject_id == stub_id)))
            .scalars()
            .all()
        )
    assert any(a.status == "ok" and "skipped" in (a.error or "") for a in audit)


async def test_apply_records_provider_unavailable(
    test_engine: AsyncEngine,
) -> None:
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    async with sm() as s:
        stub = EtvAssembly(
            organization_id=org.id,
            property_id=prop.id,
            title="...",
            description="...",
            location="...",
            scheduled_start=datetime(2026, 4, 2, 16, 0, tzinfo=UTC),
            scheduled_end=datetime(2026, 4, 2, 19, 0, tzinfo=UTC),
            status=AssemblyStatus.EINGELADEN,
        )
        s.add(stub)
        await s.commit()
        stub_id = stub.id

    provider = _MockProvider(
        _make_payload(),
        raise_with=LLMProviderUnavailableError("no key configured"),
    )

    async with sm() as s:
        outcome = await extract_and_apply(
            s,
            assembly_id=stub_id,
            pdf_bytes=b"x",
            source_document_id=None,
            provider=provider,  # type: ignore[arg-type]
        )
        await s.commit()
    assert outcome == "skipped_provider_unavailable"

    async with sm() as s:
        # Stub fields untouched.
        row = await s.get(EtvAssembly, stub_id)
        assert row is not None
        assert row.auto_extracted_at is None
        # Audit log captured the skip with a recognisable status.
        audit = (
            (await s.execute(select(LLMAuditLog).where(LLMAuditLog.subject_id == stub_id)))
            .scalars()
            .all()
        )
    assert any(a.status == "skipped_provider_unavailable" for a in audit)


async def test_apply_records_parse_error_and_reraises(
    test_engine: AsyncEngine,
) -> None:
    """A parse failure is non-retryable (LLM output didn't match the
    schema). We record + re-raise so the Celery task fails loudly
    rather than silently swallowing bad output."""
    org = await make_org(test_engine)
    prop = await make_property(test_engine, org=org)
    sm = async_sessionmaker(test_engine, expire_on_commit=False)

    async with sm() as s:
        stub = EtvAssembly(
            organization_id=org.id,
            property_id=prop.id,
            title="...",
            description="...",
            location="...",
            scheduled_start=datetime(2026, 4, 2, 16, 0, tzinfo=UTC),
            scheduled_end=datetime(2026, 4, 2, 19, 0, tzinfo=UTC),
            status=AssemblyStatus.EINGELADEN,
        )
        s.add(stub)
        await s.commit()
        stub_id = stub.id

    provider = _MockProvider(
        _make_payload(),
        raise_with=LLMParseError("hallucinated agenda"),
    )

    async with sm() as s:
        with pytest.raises(LLMParseError):
            await extract_and_apply(
                s,
                assembly_id=stub_id,
                pdf_bytes=b"x",
                source_document_id=None,
                provider=provider,  # type: ignore[arg-type]
            )
        # Even with the raise, the audit insert in this session is
        # rolled back unless we commit the audit-only write. The
        # service inserts the audit row BEFORE raising — verify it's
        # in the session even though the test re-raised before commit.
        # (In production, the Celery wrapper catches + commits the
        # audit row separately.)
        pending_audit = [obj for obj in s.new if isinstance(obj, LLMAuditLog)]
    assert any(a.status == "parse_error" for a in pending_audit)
