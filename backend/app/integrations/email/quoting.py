"""Split an inbound reply into the fresh text and the quoted history.

Owners reply to ticket notifications from their mail client, which appends
the whole thread below the new text. Shown verbatim, that buries a two-line
answer under screens of "> Neue Nachricht zu Ticket …" (Laura Walter's
report, 2026-08-18). We keep the full body for the record and derive a
``visible_body`` that stops where the quote begins.

Deliberately conservative: when in doubt, keep the text. A false positive
(cutting real content) is worse than a false negative (showing a quote).
"""

from __future__ import annotations

import re

# One reply-header line = the whole tail is a quote. Covered:
#   "Wagner Hausverwaltung Support <…> schrieb am Di., 18. Aug. 2026, 10:10:"
#   "Am 18.08.2026 um 10:10 schrieb Max Mustermann:"
#   "On Tue, Aug 18, 2026 at 10:10 AM Max <m@x.de> wrote:"
#   "-----Ursprüngliche Nachricht-----" / "-----Original Message-----"
#   "Von: … Gesendet: …" Outlook block (Von: alone is too generic; we require
#   the following "Gesendet:"/"An:" line, checked in _is_outlook_block).
_HEADER_PATTERNS = [
    re.compile(r"^.{0,120}\bschrieb am\b.{0,80}:\s*$", re.IGNORECASE),
    re.compile(r"^Am\b.{0,120}\bschrieb\b.{0,120}:\s*$", re.IGNORECASE),
    re.compile(r"^On\b.{0,160}\bwrote:\s*$", re.IGNORECASE),
    re.compile(
        r"^-{2,}\s*(Ursprüngliche Nachricht|Original Message"
        r"|Weitergeleitete Nachricht|Forwarded message)\s*-{2,}\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"^_{5,}\s*$"),  # Outlook's underscore rule above the header block
]

_QUOTE_LINE = re.compile(r"^\s*>")


def _is_outlook_block(lines: list[str], i: int) -> bool:
    if not lines[i].strip().lower().startswith(("von:", "from:")):
        return False
    tail = " ".join(line.strip().lower() for line in lines[i + 1 : i + 4])
    return any(k in tail for k in ("gesendet:", "sent:", "an:", "to:"))


def split_quoted_reply(body: str) -> tuple[str, str | None]:
    """Return ``(visible, quoted)``; ``quoted`` is None when nothing was cut.

    Cut at the first reply-header line, or at the first run of ``>`` lines
    that continues to the end of the message. Trailing blank lines are
    trimmed from the visible part.
    """
    if not body:
        return body, None
    lines = body.splitlines()
    cut: int | None = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if any(p.match(stripped) for p in _HEADER_PATTERNS) or _is_outlook_block(lines, i):
            cut = i
            break
        # Gmail wraps long headers: "Name <mail> " on one line, "schrieb am
        # Di., 18. Aug. 2026, 10:10:" on the next. Match the joined pair and
        # cut at the FIRST of the two lines so the sender doesn't dangle.
        if i + 1 < len(lines):
            joined = f"{stripped} {lines[i + 1].strip()}"
            if any(p.match(joined) for p in _HEADER_PATTERNS[:3]):
                cut = i
                break

    if cut is None:
        # A '>' block that runs to the end (allowing blank lines inside).
        j = len(lines)
        while j > 0 and (not lines[j - 1].strip() or _QUOTE_LINE.match(lines[j - 1])):
            j -= 1
        quoted_tail = [ln for ln in lines[j:] if ln.strip()]
        if quoted_tail and all(_QUOTE_LINE.match(ln) for ln in quoted_tail):
            cut = j

    if cut is None:
        return body, None

    # Never cut everything: if there is no fresh text at all, keep the body.
    visible = "\n".join(lines[:cut]).rstrip()
    if not visible.strip():
        return body, None
    quoted = "\n".join(lines[cut:]).strip()
    return visible, quoted or None
