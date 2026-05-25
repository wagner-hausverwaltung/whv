"""Lifecycle helpers for announcements (Mitteilungen).

Shared by the admin + owner API and the Celery beat publish task. None
of these functions commit — the caller decides commit boundaries so an
HTTP 4xx can roll back cleanly and the beat task can commit per
announcement.

Lifecycle in one paragraph: create → `scheduled_publish_at = now() +
EDITORIAL_DELAY`. Every PATCH while unpublished resets it (each edit
buys another 10-min review window). `publish_now()` collapses the
remaining delay to zero so the next beat tick fans out. Once
`notification_sent_at` is set, the row is "published"; edits to title
/ body / audience still apply (and bump `updated_at`) but the timer
is frozen — those changes are visible on the portal immediately.

Audience filter: three independent booleans (eigentuemer / mieter /
beirat). Fan-out resolves "users on this property whose role matches
at least one audience flag". VERWALTER never receives the publish
email — they sent it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Announcement,
    AnnouncementAttachment,
    AnnouncementComment,
    AnnouncementCommentVersion,
    AnnouncementSendAttempt,
    AnnouncementUnit,
    Contact,
    Contract,
    ContractContact,
    SendAttemptStatus,
    User,
    UserRole,
)
from app.schemas.announcement import (
    AnnouncementCreateRequest,
    AnnouncementUpdateRequest,
)

logger = logging.getLogger(__name__)


# Editorial buffer between "admin saved" and "users get notified". Each
# unpublished-state edit resets the countdown to give the admin another
# review window. Tuned to 10 min per spec — short enough that admins
# don't forget the message is queued, long enough to catch typos.
EDITORIAL_DELAY = timedelta(minutes=10)
# Threshold for "this announcement was edited after publish". Anything
# inside this window is treated as the natural updated_at-bump on
# publish itself (notification_sent_at + a few hundred ms). Anything
# beyond it is a genuine user-visible edit and earns the "Bearbeitet"
# indicator on the portal.
EDIT_INDICATOR_GRACE = timedelta(seconds=60)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------
# Pure helpers — no DB access. Tested directly.
# ---------------------------------------------------------------------


def is_published(announcement: Announcement) -> bool:
    """True once the fan-out task has stamped notification_sent_at."""
    return announcement.notification_sent_at is not None


def is_edited_post_publish(announcement: Announcement) -> bool:
    """True when `updated_at` is meaningfully after `notification_sent_at`.

    The grace window absorbs the trivial bump that happens during
    publish itself (the worker writes notification_sent_at and that
    counts as an UPDATE, advancing updated_at by a few hundred ms).
    """
    if announcement.notification_sent_at is None:
        return False
    return announcement.updated_at > (announcement.notification_sent_at + EDIT_INDICATOR_GRACE)


def audience_roles(announcement: Announcement) -> set[UserRole]:
    """The set of UserRole values an announcement should fan out to."""
    out: set[UserRole] = set()
    if announcement.audience_eigentuemer:
        out.add(UserRole.EIGENTUEMER)
    if announcement.audience_mieter:
        out.add(UserRole.MIETER)
    if announcement.audience_beirat:
        out.add(UserRole.BEIRAT)
    return out


def audience_matches_role(announcement: Announcement, role: UserRole) -> bool:
    """True if a user with this role is in the announcement's audience.

    VERWALTER is never in any audience (they sent it). Owner-side reads
    of an announcement always call this to decide visibility.
    """
    return role in audience_roles(announcement)


# ---------------------------------------------------------------------
# Create / update / publish — write helpers. Caller commits.
# ---------------------------------------------------------------------


def create_announcement(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
    author: User,
    payload: AnnouncementCreateRequest,
) -> Announcement:
    """Build a new Announcement row and add it to the session.

    Sets `scheduled_publish_at = now() + EDITORIAL_DELAY`. Caller is
    responsible for org-scope + property-belongs-to-org + author-is-
    VERWALTER checks before calling.
    """
    row = Announcement(
        organization_id=organization_id,
        property_id=property_id,
        created_by_user_id=author.id,
        title=payload.title,
        body=payload.body,
        audience_eigentuemer=payload.audience_eigentuemer,
        audience_mieter=payload.audience_mieter,
        audience_beirat=payload.audience_beirat,
        scheduled_publish_at=_now() + EDITORIAL_DELAY,
    )
    session.add(row)
    return row


def apply_update(announcement: Announcement, payload: AnnouncementUpdateRequest) -> None:
    """Apply a PATCH payload to an existing Announcement in place.

    Pure mutation — no DB I/O, caller commits. If the announcement is
    not yet published, also resets `scheduled_publish_at` to
    `now() + EDITORIAL_DELAY` so each edit buys the admin another
    review window. Once published the timer stays frozen.

    Raises ValueError if the patch would leave the audience with zero
    selected roles (resolved against current values, since a partial
    PATCH may set only one flag).
    """
    if payload.title is not None:
        announcement.title = payload.title
    if payload.body is not None:
        announcement.body = payload.body

    # Resolve the post-patch audience state and validate at-least-one.
    eig = (
        payload.audience_eigentuemer
        if payload.audience_eigentuemer is not None
        else announcement.audience_eigentuemer
    )
    mie = (
        payload.audience_mieter
        if payload.audience_mieter is not None
        else announcement.audience_mieter
    )
    bei = (
        payload.audience_beirat
        if payload.audience_beirat is not None
        else announcement.audience_beirat
    )
    if not (eig or mie or bei):
        raise ValueError(
            "At least one audience flag (Eigentümer / Mieter / Beirat) must remain selected"
        )
    announcement.audience_eigentuemer = eig
    announcement.audience_mieter = mie
    announcement.audience_beirat = bei

    # Editorial-buffer reset only while unpublished. Post-publish the
    # timer is frozen — `notification_sent_at` remains the source of
    # truth for "when did users actually see this".
    if not is_published(announcement):
        announcement.scheduled_publish_at = _now() + EDITORIAL_DELAY


def publish_now(announcement: Announcement) -> None:
    """Schedule the announcement for fan-out on the next beat tick.

    Sets `scheduled_publish_at = now()`; the partial index entry
    becomes immediately due, the Celery beat picks it up within a
    minute. No-op if already published.
    """
    if is_published(announcement):
        return
    announcement.scheduled_publish_at = _now()


def soft_delete(announcement: Announcement) -> None:
    """Mark the announcement deleted_at = now().

    Cascades visibility — non-admin reads filter `deleted_at IS NULL`,
    and the publish-due partial index drops the row, so a soft-delete
    before publish silently prevents the fan-out. Comments stay in the
    DB (CASCADE) but become invisible by virtue of the parent being
    hidden.
    """
    if announcement.deleted_at is None:
        announcement.deleted_at = _now()


# ---------------------------------------------------------------------
# Read helpers — list / get with the right scope filters.
# ---------------------------------------------------------------------


async def list_for_property_admin(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Announcement], int]:
    """Admin queue for a property — all announcements including drafts.

    Soft-deleted rows are excluded; admin can't unhide via this list
    (would need a separate "Papierkorb" endpoint, out of scope v1).
    """
    base = select(Announcement).where(
        Announcement.organization_id == organization_id,
        Announcement.property_id == property_id,
        Announcement.deleted_at.is_(None),
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = (
        await session.scalars(
            base.order_by(Announcement.scheduled_publish_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)


async def list_for_org_admin(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Announcement], int]:
    """Cross-property admin queue.

    Same shape as `list_for_property_admin` but doesn't constrain by
    property_id. Used by the org-wide /admin/announcements page so a
    Verwalter can see every Mitteilung they've ever sent without
    drilling into each property.
    """
    base = select(Announcement).where(
        Announcement.organization_id == organization_id,
        Announcement.deleted_at.is_(None),
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = (
        await session.scalars(
            base.order_by(Announcement.scheduled_publish_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)


async def list_for_property_owner(
    session: AsyncSession,
    *,
    user: User,
    property_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Announcement], int]:
    """Portal list: published, audience-matched, not-deleted.

    Caller is expected to have already confirmed the user can access
    `property_id` via `_visible_properties_stmt`. Audience filter is
    applied here so a user with role=EIGENTUEMER never sees a Mieter-
    only Mitteilung even if their account technically belongs to the
    property.
    """
    base = select(Announcement).where(
        Announcement.property_id == property_id,
        Announcement.deleted_at.is_(None),
        Announcement.notification_sent_at.isnot(None),
    )
    if user.role == UserRole.EIGENTUEMER:
        base = base.where(Announcement.audience_eigentuemer.is_(True))
    elif user.role == UserRole.MIETER:
        base = base.where(Announcement.audience_mieter.is_(True))
    elif user.role == UserRole.BEIRAT:
        base = base.where(Announcement.audience_beirat.is_(True))
    else:
        # VERWALTER doesn't normally hit the owner endpoint — but if
        # they do (e.g. dogfooding their own portal), show them
        # nothing. The admin list is the right surface for them.
        return [], 0

    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = (
        await session.scalars(
            base.order_by(Announcement.notification_sent_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)


async def get_admin(
    session: AsyncSession,
    *,
    announcement_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> Announcement | None:
    """Fetch by id, scoped to the caller's org. Soft-deleted rows
    excluded — admin doesn't get to peek into the trash via this
    helper. Returns None on miss (caller maps to 404)."""
    row: Announcement | None = await session.scalar(
        select(Announcement).where(
            Announcement.id == announcement_id,
            Announcement.organization_id == organization_id,
            Announcement.deleted_at.is_(None),
        )
    )
    return row


async def get_owner(
    session: AsyncSession,
    *,
    announcement_id: uuid.UUID,
    user: User,
) -> Announcement | None:
    """Fetch by id for a portal viewer.

    Returns None unless the announcement is published, not deleted,
    matches the viewer's role audience, and the viewer can access its
    property. Property-access check is intentionally NOT done here —
    the caller (route handler) has already loaded the visible-property
    set via `_visible_properties_stmt`; passing it through would
    couple this module to the API layer. Instead, this returns the row
    if all *announcement-side* gates pass, and the caller asserts
    property visibility separately.
    """
    row: Announcement | None = await session.scalar(
        select(Announcement).where(
            Announcement.id == announcement_id,
            Announcement.deleted_at.is_(None),
            Announcement.notification_sent_at.isnot(None),
        )
    )
    if row is None:
        return None
    if not audience_matches_role(row, user.role):
        return None
    return row


# ---------------------------------------------------------------------
# Attachment + comment helpers.
# ---------------------------------------------------------------------


async def list_attachments(
    session: AsyncSession, announcement_id: uuid.UUID
) -> list[AnnouncementAttachment]:
    rows = (
        await session.scalars(
            select(AnnouncementAttachment)
            .where(AnnouncementAttachment.announcement_id == announcement_id)
            .order_by(AnnouncementAttachment.created_at.asc())
        )
    ).all()
    return list(rows)


async def list_comments(
    session: AsyncSession,
    announcement_id: uuid.UUID,
    *,
    include_hidden: bool,
) -> list[AnnouncementComment]:
    """Load comments chronologically.

    Owner-facing reads pass `include_hidden=False` to filter moderated
    rows out at the DB level. Admin reads pass `True` so they can see
    + unhide.
    """
    stmt = (
        select(AnnouncementComment)
        .where(AnnouncementComment.announcement_id == announcement_id)
        .order_by(AnnouncementComment.created_at.asc())
    )
    if not include_hidden:
        stmt = stmt.where(AnnouncementComment.is_hidden.is_(False))
    rows = (await session.scalars(stmt)).all()
    return list(rows)


def add_comment(
    session: AsyncSession,
    *,
    announcement: Announcement,
    author: User,
    body: str,
) -> AnnouncementComment:
    """Append a comment to a published announcement. Caller asserts
    visibility (audience match + property participation) before
    calling; this function only handles the DB write."""
    comment = AnnouncementComment(
        announcement_id=announcement.id,
        author_user_id=author.id,
        body=body,
    )
    session.add(comment)
    return comment


def edit_comment(
    session: AsyncSession,
    *,
    comment: AnnouncementComment,
    author: User,
    new_body: str,
) -> None:
    """Author-only inline edit. Captures the prior body into
    `announcement_comment_versions` *before* mutating, then writes
    the new body and stamps `edited_at = now()`. Raises ValueError
    if the requester isn't the original author — admins use the
    moderation path, not this one.

    Hidden comments are intentionally editable too (admin can ask the
    author to fix a problem before unhiding); the portal hides them
    from non-admin reads anyway so an edit while hidden has no
    user-visible side-effect until the admin un-hides.

    A no-op edit (new body identical to current) still writes a
    version row + bumps edited_at. Detecting "no change" silently
    is more confusing than the duplicate row: the audit trail then
    shows the author hit Save, which is a useful signal.
    """
    if comment.author_user_id != author.id:
        raise ValueError("Only the comment author can edit it")
    session.add(
        AnnouncementCommentVersion(
            comment_id=comment.id,
            body=comment.body,
            author_user_id=author.id,
        )
    )
    comment.body = new_body
    comment.edited_at = _now()


async def list_comment_versions(
    session: AsyncSession, comment_id: uuid.UUID
) -> list[AnnouncementCommentVersion]:
    """All prior bodies of a comment, newest first. Each row is the
    body that was active *before* the edit recorded at `recorded_at`.
    The current (latest) body lives on the parent comment row."""
    rows = (
        await session.scalars(
            select(AnnouncementCommentVersion)
            .where(AnnouncementCommentVersion.comment_id == comment_id)
            .order_by(AnnouncementCommentVersion.recorded_at.desc())
        )
    ).all()
    return list(rows)


def set_comment_hidden(
    *,
    comment: AnnouncementComment,
    is_hidden: bool,
    moderator: User,
    reason: str | None,
) -> None:
    """Toggle moderation. Setting `is_hidden=False` clears the
    `hidden_*` audit fields; setting True stamps them with `moderator`
    + `now()` + the optional reason."""
    if is_hidden:
        comment.is_hidden = True
        comment.hidden_at = _now()
        comment.hidden_by_user_id = moderator.id
        comment.hidden_reason = reason
    else:
        comment.is_hidden = False
        comment.hidden_at = None
        comment.hidden_by_user_id = None
        comment.hidden_reason = None


# ---------------------------------------------------------------------
# Celery publish-task support: find due rows, resolve recipients, mark
# published.
# ---------------------------------------------------------------------


async def find_due_for_publish(
    session: AsyncSession, *, now: datetime | None = None
) -> list[Announcement]:
    """Return announcements ready for fan-out.

    Hits the `ix_announcements_due_for_publish` partial index. Caller
    iterates and calls `resolve_recipients` + `mark_published` per
    row.
    """
    cutoff = now or _now()
    rows = (
        await session.scalars(
            select(Announcement)
            .where(
                Announcement.scheduled_publish_at <= cutoff,
                Announcement.notification_sent_at.is_(None),
                Announcement.deleted_at.is_(None),
            )
            .order_by(Announcement.scheduled_publish_at.asc())
        )
    ).all()
    return list(rows)


async def resolve_recipients(session: AsyncSession, announcement: Announcement) -> list[User]:
    """Active users matched by the announcement's audience + (optional)
    per-unit narrowing.

    Behaviour split:
      - No `announcement_units` rows for this announcement →
        property-wide-by-role: every active user on a contract for
        the property whose `User.role` is in the audience set.
      - One or more `announcement_units` rows → same query but
        Contract.unit_id is constrained to the listed unit set. A
        contract that covers a different unit on the same property
        no longer leaks.

    De-duped by user.id — a user with multiple matching contracts
    still gets one email.
    """
    roles = audience_roles(announcement)
    if not roles:
        return []

    unit_ids = await list_targeted_unit_ids(session, announcement.id)

    stmt = (
        select(User)
        .join(Contact, Contact.impower_id == User.contact_id_impower)
        .join(ContractContact, ContractContact.contact_id == Contact.id)
        .join(Contract, Contract.id == ContractContact.contract_id)
        .where(
            Contract.property_id == announcement.property_id,
            User.deleted_at.is_(None),
            User.contact_id_impower.isnot(None),
            User.role.in_(list(roles)),
        )
        .distinct()
    )
    if unit_ids:
        stmt = stmt.where(Contract.unit_id.in_(unit_ids))

    rows = (await session.scalars(stmt)).all()
    return list(rows)


async def list_targeted_unit_ids(
    session: AsyncSession, announcement_id: uuid.UUID
) -> list[uuid.UUID]:
    """All unit_ids the announcement is narrowed to. Empty list = the
    announcement is property-wide-by-role (default)."""
    rows = (
        await session.scalars(
            select(AnnouncementUnit.unit_id).where(
                AnnouncementUnit.announcement_id == announcement_id
            )
        )
    ).all()
    return list(rows)


async def replace_targeted_units(
    session: AsyncSession,
    *,
    announcement: Announcement,
    unit_ids: list[uuid.UUID],
) -> None:
    """Drop existing target-unit rows + insert the new set.

    Caller is responsible for validating that every unit_id belongs
    to `announcement.property_id` before calling (otherwise an admin
    could narrow an announcement to a unit on a totally different
    property and confuse the fan-out — the join would simply return
    zero users, but the audit trail would look bizarre).
    """
    from sqlalchemy import delete

    await session.execute(
        delete(AnnouncementUnit).where(AnnouncementUnit.announcement_id == announcement.id)
    )
    for uid in unit_ids:
        session.add(
            AnnouncementUnit(
                announcement_id=announcement.id,
                unit_id=uid,
            )
        )


async def resolve_comment_notification_recipients(
    session: AsyncSession,
    *,
    announcement: Announcement,
    new_comment: AnnouncementComment,
) -> list[User]:
    """Recipients for the "new comment on Mitteilung X" email.

    Two sets, unioned + de-duped + minus the new commenter:
      - Every active VERWALTER in the announcement's org (always — the
        admin team owns the conversation).
      - Every distinct author of any *non-hidden* prior comment on
        the same announcement (thread participants).

    Hidden comments don't grant their author membership — a user
    whose post was moderated away shouldn't keep getting pinged about
    new replies they can't see.
    """
    # Active VERWALTER for this org.
    verwalter = (
        await session.scalars(
            select(User).where(
                User.organization_id == announcement.organization_id,
                User.role == UserRole.VERWALTER,
                User.deleted_at.is_(None),
                User.id != new_comment.author_user_id,
            )
        )
    ).all()

    # Prior commenters with non-hidden visibility — distinct users.
    prior_author_ids_rows = (
        await session.execute(
            select(AnnouncementComment.author_user_id)
            .where(
                AnnouncementComment.announcement_id == announcement.id,
                AnnouncementComment.is_hidden.is_(False),
                AnnouncementComment.id != new_comment.id,
                AnnouncementComment.author_user_id != new_comment.author_user_id,
            )
            .distinct()
        )
    ).all()
    prior_author_ids = [row[0] for row in prior_author_ids_rows]

    prior_users: list[User] = []
    if prior_author_ids:
        prior_users = list(
            (
                await session.scalars(
                    select(User).where(
                        User.id.in_(prior_author_ids),
                        User.deleted_at.is_(None),
                    )
                )
            ).all()
        )

    seen: set[uuid.UUID] = set()
    merged: list[User] = []
    for u in [*verwalter, *prior_users]:
        if u.id in seen:
            continue
        seen.add(u.id)
        merged.append(u)
    return merged


async def resolve_active_recipients(
    session: AsyncSession, announcement: Announcement
) -> list[tuple[User | None, str]]:
    """Final recipient set for the next send.

    Applies the admin's per-Mitteilung override on top of the
    auto-resolved set:

        active = (auto_users minus excluded_user_ids) plus extra_emails

    Returns a list of (User-or-None, email) tuples. For auto-resolved
    rows the User is set so the caller can pass it to
    record_send_attempt; for extras (no portal account) User is None
    and the email is captured straight from `extra_emails`.

    De-duped by email — an admin who adds an extra that happens to
    match an auto-resolved user's address still gets one send.
    """
    auto = await resolve_recipients(session, announcement)
    excluded = set(announcement.excluded_user_ids or [])

    out: list[tuple[User | None, str]] = []
    seen_emails: set[str] = set()
    for user in auto:
        if user.id in excluded:
            continue
        if not user.email or user.email in seen_emails:
            continue
        seen_emails.add(user.email)
        out.append((user, user.email))
    for raw in announcement.extra_emails or []:
        email = raw.strip()
        if not email or email in seen_emails:
            continue
        seen_emails.add(email)
        out.append((None, email))
    return out


async def build_recipient_preview(
    session: AsyncSession, announcement: Announcement
) -> tuple[list[dict[str, str | bool | None]], list[str]]:
    """Render the admin's recipient-editor view.

    Returns `(items, active_emails)`. Each `item` is a dict the
    Pydantic schema can ingest directly — using a dict (vs. dataclass)
    keeps the helper free of layering concerns when called from the
    API handler.
    """
    auto = await resolve_recipients(session, announcement)
    excluded = set(announcement.excluded_user_ids or [])

    items: list[dict[str, str | bool | None]] = []
    seen_emails: set[str] = set()
    active_emails: list[str] = []
    for user in auto:
        is_excluded = user.id in excluded
        item: dict[str, str | bool | None] = {
            "kind": "AUTO_USER",
            "email": user.email,
            "user_id": str(user.id),
            "user_role": user.role.value if user.role else None,
            "excluded": is_excluded,
        }
        items.append(item)
        if not is_excluded and user.email and user.email not in seen_emails:
            seen_emails.add(user.email)
            active_emails.append(user.email)

    for raw in announcement.extra_emails or []:
        email = raw.strip()
        if not email:
            continue
        items.append(
            {
                "kind": "EXTRA_EMAIL",
                "email": email,
                "user_id": None,
                "user_role": None,
                "excluded": False,
            }
        )
        if email not in seen_emails:
            seen_emails.add(email)
            active_emails.append(email)

    return items, active_emails


def apply_recipient_overrides(
    announcement: Announcement,
    *,
    excluded_user_ids: list[uuid.UUID] | None,
    extra_emails: list[str] | None,
) -> None:
    """PATCH-style writer for the override columns. None = leave; an
    explicit list (incl. empty) replaces the column."""
    if excluded_user_ids is not None:
        announcement.excluded_user_ids = list(excluded_user_ids)
    if extra_emails is not None:
        # Normalise: trim whitespace, drop empties, de-dupe in order.
        seen: set[str] = set()
        out: list[str] = []
        for raw in extra_emails:
            email = raw.strip()
            if not email or email in seen:
                continue
            seen.add(email)
            out.append(email)
        announcement.extra_emails = out


def mark_published(announcement: Announcement) -> None:
    """Stamp `notification_sent_at = now()` so the row drops out of
    the publish-due partial index. Caller commits."""
    announcement.notification_sent_at = _now()


def record_send_attempt(
    session: AsyncSession,
    *,
    announcement: Announcement,
    recipient_user: User | None,
    recipient_email: str,
    status: SendAttemptStatus,
    error_message: str | None = None,
    error_code: str | None = None,
) -> AnnouncementSendAttempt:
    """Append a per-recipient send-attempt row. Caller commits.

    `recipient_user` is the resolved user at send time (or None for
    a replay where the user was deleted). `recipient_email` is what
    actually went out. On FAILED, `error_message` carries the
    truncated EmailError string and `error_code` carries the stable
    category ("rate_limited", "no_api_key", "upstream") so the SPA
    can branch on a known set rather than free-text parsing."""
    row = AnnouncementSendAttempt(
        announcement_id=announcement.id,
        recipient_user_id=recipient_user.id if recipient_user else None,
        recipient_email=recipient_email,
        status=status,
        error_message=error_message[:500] if error_message else None,
        error_code=error_code,
    )
    session.add(row)
    return row


async def list_send_attempts(
    session: AsyncSession, announcement_id: uuid.UUID
) -> list[AnnouncementSendAttempt]:
    """All attempts for an announcement, newest first."""
    rows = (
        await session.scalars(
            select(AnnouncementSendAttempt)
            .where(AnnouncementSendAttempt.announcement_id == announcement_id)
            .order_by(AnnouncementSendAttempt.attempted_at.desc())
        )
    ).all()
    return list(rows)


async def list_failed_recipients_for_resend(
    session: AsyncSession, announcement_id: uuid.UUID
) -> list[str]:
    """The set of recipient emails whose latest attempt is FAILED.

    Used by the admin "Erneut senden" button — we only retry the
    addresses still in failure state (a row that previously failed
    but later succeeded is left alone).
    """
    rows = (
        await session.scalars(
            select(AnnouncementSendAttempt)
            .where(AnnouncementSendAttempt.announcement_id == announcement_id)
            .order_by(AnnouncementSendAttempt.attempted_at.desc())
        )
    ).all()

    latest_by_email: dict[str, SendAttemptStatus] = {}
    for row in rows:
        if row.recipient_email not in latest_by_email:
            latest_by_email[row.recipient_email] = row.status
    return [
        email
        for email, status_value in latest_by_email.items()
        if status_value == SendAttemptStatus.FAILED
    ]
