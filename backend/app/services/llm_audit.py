"""LLM audit log helpers.

One entry point — `record()` — that the extraction / chat / RAG paths
all call after their LLM provider returns (or raises). Keeps the
audit shape consistent across features without each one re-deriving
"how do I log this call".

This file deliberately doesn't depend on the LLMProvider classes
themselves (only on the `LLMCallStats` dataclass and well-known
exception types). That avoids an import cycle and means tests for the
provider modules don't need a DB session.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.llm.base import (
    LLMCallStats,
    LLMParseError,
    LLMProviderUnavailableError,
)
from app.models import LLMAuditLog

AuditStatus = Literal[
    "ok",
    "skipped_provider_unavailable",
    "parse_error",
    "error",
]


async def record(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    purpose: str,
    provider: str,
    status: AuditStatus,
    stats: LLMCallStats | None = None,
    subject_kind: str | None = None,
    subject_id: uuid.UUID | None = None,
    error: str | None = None,
) -> None:
    """Insert one audit row. Caller commits.

    `stats` may be None on short-circuit / failure paths where we
    never got a real response — store zeros so dashboards can still
    `SUM(input_tokens)` cleanly. Model name in that case falls back
    to the provider name (e.g. "gemini" / "none") so the row is
    still attributable to a vendor.
    """
    session.add(
        LLMAuditLog(
            organization_id=organization_id,
            purpose=purpose,
            provider=provider,
            model=stats.model if stats else provider,
            input_tokens=stats.input_tokens if stats else 0,
            output_tokens=stats.output_tokens if stats else 0,
            latency_ms=stats.latency_ms if stats else 0,
            status=status,
            subject_kind=subject_kind,
            subject_id=subject_id,
            error=(error[:500] if error else None),
        )
    )


def status_for_exception(exc: BaseException) -> AuditStatus:
    """Map a provider exception to the audit `status` column. Used
    by the extraction Celery task to keep the mapping in one place."""
    if isinstance(exc, LLMProviderUnavailableError):
        return "skipped_provider_unavailable"
    if isinstance(exc, LLMParseError):
        return "parse_error"
    return "error"
