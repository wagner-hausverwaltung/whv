"""Per-user notification-preference helpers.

Three jobs:
  1. `get_effective_settings` — load a user's rows and fill the
     opt-out default (all on) for every category that has no row, so
     the API always returns the full matrix.
  2. `set_settings` — upsert the rows from a PUT.
  3. `filter_user_ids` — the fan-out gate: given a recipient list, a
     category and a channel, drop only the users who EXPLICITLY
     disabled that channel for that category. Users with no row stay
     in (opt-out), so nobody silently loses notifications.

All helpers are session-in / caller-commits, matching the other
service modules.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    NotificationCategory,
    NotificationChannel,
    UserNotificationPreference,
)

# The canonical category order the API + UI render in.
ALL_CATEGORIES: tuple[NotificationCategory, ...] = (
    NotificationCategory.ANNOUNCEMENT,
    NotificationCategory.TICKET,
    NotificationCategory.ETV_COMMENT,
    NotificationCategory.ETV_INVITATION,
    NotificationCategory.DOCUMENT,
    NotificationCategory.INVOICE,
)


async def get_effective_settings(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> dict[NotificationCategory, tuple[bool, bool]]:
    """Return {category: (push_enabled, email_enabled)} for every
    category, defaulting missing rows to (True, True)."""
    rows = (
        await session.scalars(
            select(UserNotificationPreference).where(UserNotificationPreference.user_id == user_id)
        )
    ).all()
    by_cat = {r.category: (r.push_enabled, r.email_enabled) for r in rows}
    return {cat: by_cat.get(cat, (True, True)) for cat in ALL_CATEGORIES}


async def set_settings(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    settings: Mapping[NotificationCategory, tuple[bool, bool]],
) -> None:
    """Upsert one row per supplied category. Caller commits."""
    for category, (push, email) in settings.items():
        stmt = (
            pg_insert(UserNotificationPreference)
            .values(
                user_id=user_id,
                category=category,
                push_enabled=push,
                email_enabled=email,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "category"],
                set_={
                    "push_enabled": push,
                    "email_enabled": email,
                    "updated_at": func.now(),
                },
            )
        )
        await session.execute(stmt)


async def filter_user_ids(
    session: AsyncSession,
    *,
    user_ids: Sequence[uuid.UUID],
    category: NotificationCategory,
    channel: NotificationChannel,
) -> list[uuid.UUID]:
    """Drop only the users who explicitly turned this (category,
    channel) OFF. Users without a row stay in (opt-out). Order of the
    input list is preserved.
    """
    if not user_ids:
        return []
    channel_col = (
        UserNotificationPreference.push_enabled
        if channel == NotificationChannel.PUSH
        else UserNotificationPreference.email_enabled
    )
    disabled = set(
        (
            await session.scalars(
                select(UserNotificationPreference.user_id).where(
                    UserNotificationPreference.user_id.in_(list(user_ids)),
                    UserNotificationPreference.category == category,
                    channel_col.is_(False),
                )
            )
        ).all()
    )
    return [uid for uid in user_ids if uid not in disabled]
