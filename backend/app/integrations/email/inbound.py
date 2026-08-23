"""SES → SNS inbound-email parser.

When AWS SES receives an email matching our receipt rule, it publishes a
JSON blob to the SNS topic. The blob has:

  - `mail` envelope with parsed headers + `commonHeaders` (sender, subject,
    Message-ID, etc.)
  - `receipt.spamVerdict` / `virusVerdict` — we drop on FAIL
  - `content`: the raw RFC 5322 MIME message (string, up to ~150 KB inline;
    larger goes to S3, which we don't support in v1)

This module turns that into a `ParsedInboundEmail` dataclass + extracts the
ticket short-id reference from the subject (`[#abc12345]`).

Ticket creation / lookup / append happens in the webhook handler — this
module deals only with the wire format.
"""

from __future__ import annotations

import email
import re
from dataclasses import dataclass
from email.message import Message
from email.utils import parseaddr
from typing import Any

# `[#xxxxxxxxxxxxxxxx]` where the 16 hex chars are the first 16 hex chars of
# a ticket UUID (without dashes), lowercase. We use 16 (not 8) because UUIDv7
# packs a millisecond timestamp in the first 12 hex chars; an 8-char prefix
# collides for ~65 seconds, which is fatal for tests that create two tickets
# in quick succession.
# Thread tag in the subject: 6 hex chars = current scheme (last 6 of the
# ticket UUID, see email/tickets.py::ticket_tag); 16 hex chars = legacy prefix
# tag still present on older mails that owners may reply to months later.
_TICKET_REF_RE = re.compile(r"\[#([a-f0-9]{16}|[a-f0-9]{6})\]", re.IGNORECASE)
# Full ticket UUID from the body footer of our notifications ("Ticket-ID: …"),
# usually quoted back in replies — the unambiguous fallback for the short tag.
_TICKET_ID_RE = re.compile(
    r"Ticket-ID:\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class S3Ref:
    """Pointer to the raw MIME body stored in S3 by the SES S3 action."""

    bucket: str
    key: str


@dataclass(frozen=True)
class ParsedInboundAttachment:
    """One file lifted from the email's MIME tree.

    Only the bare minimum the persistence layer needs — the upload
    helper handles extension validation + storage. We don't try to
    canonicalise filenames here; the webhook hands them to
    `write_attachment` which is the security boundary.
    """

    filename: str
    mime_type: str | None
    content: bytes


@dataclass(frozen=True)
class ParsedInboundEmail:
    """Result of parsing one SES-published email payload."""

    sender_email: str  # bare address from "From:", lowercased
    subject: str  # full subject including any [#ref] prefix
    ticket_ref: str | None  # 6-char (current) / 16-char (legacy) hex tag from the subject
    message_id: str | None  # RFC 5322 Message-ID (incl. angle brackets) if present
    in_reply_to: str | None  # In-Reply-To header
    references: str | None  # References header (full chain, space-separated)
    body: str  # plaintext body, after multipart/HTML stripping
    spam_pass: bool  # SES spam verdict — false → drop
    virus_pass: bool  # SES virus verdict — false → drop
    # Files extracted from MIME parts marked `Content-Disposition:
    # attachment` (or inline images that aren't part of the visible
    # body). Empty tuple when the message had none — keeps the call site
    # branch-free.
    attachments: tuple[ParsedInboundAttachment, ...] = ()
    # Envelope recipients (mail.destination), lowercased — used to route
    # anfragen@ inquiries to the offer pipeline instead of the ticket flow.
    recipients: tuple[str, ...] = ()
    # Full ticket UUID quoted from our "Ticket-ID: …" footer, if the reply
    # carries one — resolves the thread when the short subject tag can't.
    ticket_id_hint: str | None = None


class InboundEmailParseError(Exception):
    """Raised for malformed SES payloads we cannot safely process."""


def extract_ticket_ref(subject: str) -> str | None:
    """Return the hex ticket tag from `subject` (6 chars current, 16 legacy),
    or None.

    Lowercased. Returns the first match — subjects with multiple refs (rare,
    e.g. forwarded chains) attribute to the first one mentioned.
    """
    match = _TICKET_REF_RE.search(subject or "")
    if match is None:
        return None
    return match.group(1).lower()


def extract_ticket_id_hint(body: str) -> str | None:
    """The full ticket UUID from a quoted "Ticket-ID: …" footer in the body,
    lowercased, or None. First occurrence wins (the most recent quote sits
    on top in every common mail client)."""
    match = _TICKET_ID_RE.search(body or "")
    if match is None:
        return None
    return match.group(1).lower()


def _verdict_pass(receipt: dict[str, Any] | None, key: str) -> bool:
    if not receipt:
        # If SES didn't even include receipt verdicts, fail-open: SES is
        # known to publish them on every Received event, so absence here
        # likely means a hand-crafted payload (test or malicious) — but
        # at this layer we only look at the receipt; signature verification
        # is the security boundary, not this.
        return True
    verdict = receipt.get(key, {})
    status = (verdict or {}).get("status", "PASS")
    return bool(status == "PASS")


def _decode_part_payload(part: Message) -> str:
    raw = part.get_payload(decode=True)
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        charset = part.get_content_charset() or "utf-8"
        try:
            return raw.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            return raw.decode("utf-8", errors="replace")
    return str(raw)


def _extract_body(message: Message) -> str:
    """Pull the best human-readable body out of a parsed MIME message.

    Order of preference:
      1. text/plain body (multipart or singlepart)
      2. text/html body, with the tags crudely stripped
      3. empty string

    No signature stripping / quoted-reply removal in v1 — the noise is
    acceptable, and reply-stripping libraries (talon, mail-parser-reply)
    add a lot of dependency surface for diminishing returns.
    """
    plain: str | None = None
    html: str | None = None

    if message.is_multipart():
        for part in message.walk():
            ctype = part.get_content_type()
            if part.get("Content-Disposition", "").lower().startswith("attachment"):
                continue
            if ctype == "text/plain" and plain is None:
                plain = _decode_part_payload(part)
            elif ctype == "text/html" and html is None:
                html = _decode_part_payload(part)
    else:
        ctype = message.get_content_type()
        if ctype == "text/plain":
            plain = _decode_part_payload(message)
        elif ctype == "text/html":
            html = _decode_part_payload(message)

    if plain is not None:
        return plain.strip()
    if html is not None:
        return _html_to_text(html).strip()
    return ""


def _extract_attachments(message: Message) -> tuple[ParsedInboundAttachment, ...]:
    """Walk the MIME tree and pull out everything that looks like a file
    the user attached: parts with `Content-Disposition: attachment`, plus
    binary parts (anything non-text) that aren't the main body. Inline
    images that come bundled in HTML signatures (`Content-Disposition:
    inline`) are skipped to avoid dumping ten Outlook logo pixels into
    every ticket; the body extractor already glosses them too.

    Returns a tuple (frozen) of dataclasses so the parse result stays
    immutable. Bytes can be large — the persistence layer is expected
    to write them straight through and drop the reference.
    """
    if not message.is_multipart():
        # Single-part bodies aren't attachments. SES sometimes delivers
        # the whole thing as one text/plain payload, in which case there's
        # nothing here to pull out.
        return ()

    out: list[ParsedInboundAttachment] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = (part.get("Content-Disposition") or "").lower()
        ctype = part.get_content_type() or ""
        is_attachment = disposition.startswith("attachment")
        # Skip text bodies (the body extractor already handled them);
        # skip inline images (signature decoration). Everything else that
        # looks like a real attachment goes through.
        if not is_attachment:
            if ctype.startswith("text/"):
                continue
            if disposition.startswith("inline"):
                continue
        payload = part.get_payload(decode=True)
        if not payload or not isinstance(payload, bytes):
            continue
        filename = part.get_filename()
        if not filename:
            # Some clients omit the filename; fall back to a synthetic
            # name so the upload layer can still validate the extension.
            # Without a sensible name we'd reject every such part.
            ext = ctype.split("/")[-1] if "/" in ctype else "bin"
            filename = f"attachment.{ext}"
        out.append(
            ParsedInboundAttachment(
                filename=filename,
                mime_type=ctype or None,
                content=payload,
            )
        )
    return tuple(out)


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENTITY_RE = re.compile(r"&(amp|lt|gt|quot|nbsp);")
_HTML_ENTITY_MAP = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "nbsp": " "}


def _html_to_text(html: str) -> str:
    """Crude HTML → text. Strips tags + decodes the handful of entities that
    matter for body readability. Good enough for ticket bodies; do not use
    for content where structure carries meaning."""
    without_tags = _HTML_TAG_RE.sub(" ", html)
    without_entities = _HTML_ENTITY_RE.sub(lambda m: _HTML_ENTITY_MAP[m.group(1)], without_tags)
    # Collapse runs of whitespace introduced by tag removal.
    return re.sub(r"\s+", " ", without_entities)


def extract_s3_ref(outer: dict[str, Any]) -> S3Ref | None:
    """Pull (bucket, key) out of receipt.action when SES used the S3 action.

    Returns None when the action isn't S3 (legacy SNS-publish path) or the
    fields aren't present. Caller still needs to fall back to embedded
    content in that case.
    """
    action = (outer.get("receipt") or {}).get("action") or {}
    if action.get("type") != "S3":
        return None
    bucket = action.get("bucketName")
    key = action.get("objectKey")
    if not bucket or not key:
        return None
    return S3Ref(bucket=bucket, key=key)


def parse_ses_sns_payload(
    message_payload: str, raw_content_override: str | None = None
) -> ParsedInboundEmail:
    """Parse the inner SES envelope (the `Message` field of the SNS payload).

    `message_payload` is the JSON-encoded string inside SNS `Message` — the
    caller has already json-decoded the outer SNS envelope and pulls out the
    `Message` field as text. Here we re-decode that string and extract the
    structured fields we care about.

    `raw_content_override` lets the webhook caller inject the raw MIME when
    SES used the S3 action (in which case `content` is not embedded in the
    SNS payload). When None, we fall back to whatever `content` is in the
    payload — which works for the legacy "Publish to SNS" action.
    """
    import json

    try:
        outer = json.loads(message_payload)
    except json.JSONDecodeError as exc:
        raise InboundEmailParseError("SNS Message is not valid JSON") from exc

    notification_type = outer.get("notificationType")
    if notification_type != "Received":
        raise InboundEmailParseError(f"Unexpected notificationType: {notification_type!r}")

    mail = outer.get("mail", {})
    receipt = outer.get("receipt", {})
    common_headers = mail.get("commonHeaders", {})
    recipients = tuple(str(r).strip().lower() for r in (mail.get("destination") or []) if r)

    raw_from = ""
    from_list = common_headers.get("from") or []
    if from_list:
        raw_from = from_list[0]
    _, sender_email = parseaddr(raw_from)
    sender_email = sender_email.strip().lower()
    if not sender_email or "@" not in sender_email:
        # Fall back to envelope-level "source" if commonHeaders.from was empty
        # or malformed; SES guarantees `source` is set on Received events.
        envelope_source = (mail.get("source") or "").strip().lower()
        if "@" in envelope_source:
            sender_email = envelope_source
        else:
            raise InboundEmailParseError("Could not extract sender address")

    subject = common_headers.get("subject", "") or ""
    ticket_ref = extract_ticket_ref(subject)

    message_id = common_headers.get("messageId")
    in_reply_to: str | None = None
    references: str | None = None

    # `headers` is a list of {"name": ..., "value": ...} dicts. We pluck the
    # threading headers manually since commonHeaders doesn't surface them.
    for header in mail.get("headers", []) or []:
        name = (header.get("name") or "").lower()
        if name == "in-reply-to":
            in_reply_to = header.get("value")
        elif name == "references":
            references = header.get("value")

    # `content` is the full raw RFC 5322 message; SES base64-encodes it when
    # the action type is "Lambda" but for "SNS" action it's plaintext UTF-8.
    # When SES uses the S3 action, `content` is absent — caller pre-fetched
    # the body from S3 and passes it via `raw_content_override`.
    raw_content = (
        raw_content_override if raw_content_override is not None else outer.get("content", "")
    )
    parsed_message = email.message_from_string(raw_content)
    body = _extract_body(parsed_message)
    attachments = _extract_attachments(parsed_message)

    return ParsedInboundEmail(
        sender_email=sender_email,
        subject=subject,
        ticket_ref=ticket_ref,
        message_id=message_id,
        in_reply_to=in_reply_to,
        references=references,
        body=body,
        spam_pass=_verdict_pass(receipt, "spamVerdict"),
        virus_pass=_verdict_pass(receipt, "virusVerdict"),
        attachments=attachments,
        recipients=recipients,
        ticket_id_hint=extract_ticket_id_hint(body),
    )
