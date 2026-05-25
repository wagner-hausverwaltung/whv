"""Tests for the SES → SNS email-inbound pipeline.

Three layers:
  1. SNS signature verifier (pure cryptography, no DB / no HTTP)
  2. SES envelope parser (pure stdlib email + json)
  3. Webhook endpoint (DB + ticket routing; signature verifier monkeypatched
     to a no-op since real SNS signatures would require AWS infrastructure)
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.constants import WHV_ORGANIZATION_ID
from app.integrations.email.client import get_email_client
from app.integrations.email.inbound import (
    InboundEmailParseError,
    extract_ticket_ref,
    parse_ses_sns_payload,
)
from app.integrations.sns import validator as sns_validator
from app.main import app
from app.models import (
    AuditLog,
    Ticket,
    TicketCategory,
    TicketMessage,
    TicketMessageSource,
    TicketStatus,
    UserRole,
)
from app.tests._factories import make_org, make_user

# --- Stubs --------------------------------------------------------------------


class _StubEmailClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
        headers: dict[str, str] | None = None,
    ) -> str:
        msg_id = f"sim-{uuid.uuid4()}"
        self.sent.append(
            {
                "to": to,
                "subject": subject,
                "html": html,
                "text": text,
                "headers": headers or {},
                "id": msg_id,
            }
        )
        return msg_id


@pytest_asyncio.fixture
async def stub_email() -> AsyncIterator[_StubEmailClient]:
    stub = _StubEmailClient()

    async def _override() -> AsyncIterator[_StubEmailClient]:
        yield stub

    app.dependency_overrides[get_email_client] = _override
    yield stub
    app.dependency_overrides.pop(get_email_client, None)


# --- 1. Signature verifier ----------------------------------------------------


def _build_test_cert_and_key() -> tuple[bytes, rsa.RSAPrivateKey]:
    """Generate a one-off self-signed cert + private key for signing test
    payloads. The verifier loads X.509 PEM bytes via `cryptography`, so
    this matches the wire format."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "sns.eu-central-1.amazonaws.com")]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC))
        .not_valid_after(datetime.now(UTC) + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM), key


def _sign_canonical(message: dict[str, Any], private_key: rsa.RSAPrivateKey) -> str:
    canonical = sns_validator._canonical_string(message)
    sig = private_key.sign(
        canonical.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode("ascii")


def _make_signed_payload(
    *,
    msg_type: str = "Notification",
    body_message: str = "hello",
    private_key: rsa.RSAPrivateKey,
    cert_url: str = "https://sns.eu-central-1.amazonaws.com/SimpleNotificationService-abc.pem",
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "Type": msg_type,
        "MessageId": str(uuid.uuid4()),
        "Message": body_message,
        "Timestamp": datetime.now(UTC).isoformat(),
        "TopicArn": "arn:aws:sns:eu-central-1:271791846925:whv-email-inbound",
        "SigningCertURL": cert_url,
        "SignatureVersion": "2",
    }
    if msg_type in ("SubscriptionConfirmation", "UnsubscribeConfirmation"):
        base["SubscribeURL"] = (
            "https://sns.eu-central-1.amazonaws.com/?Action=ConfirmSubscription&Token=xyz"
        )
        base["Token"] = "tok"
    base["Signature"] = _sign_canonical(base, private_key)
    return base


def test_signature_verifier_accepts_valid_notification() -> None:
    cert_bytes, key = _build_test_cert_and_key()
    payload = _make_signed_payload(private_key=key)
    with patch.object(sns_validator, "_fetch_cert_bytes", return_value=cert_bytes):
        sns_validator.verify(payload)  # raises on failure


def test_signature_verifier_rejects_tampered_payload() -> None:
    cert_bytes, key = _build_test_cert_and_key()
    payload = _make_signed_payload(private_key=key)
    payload["Message"] = "tampered after signing"
    with (
        patch.object(sns_validator, "_fetch_cert_bytes", return_value=cert_bytes),
        pytest.raises(sns_validator.SignatureError),
    ):
        sns_validator.verify(payload)


def test_signature_verifier_rejects_disallowed_cert_host() -> None:
    cert_bytes, key = _build_test_cert_and_key()
    payload = _make_signed_payload(
        private_key=key,
        cert_url="https://evil.example.com/SimpleNotificationService.pem",
    )
    with (
        patch.object(sns_validator, "_fetch_cert_bytes", return_value=cert_bytes),
        pytest.raises(sns_validator.SignatureError, match="host not allowed"),
    ):
        sns_validator.verify(payload)


def test_signature_verifier_rejects_non_https_url() -> None:
    cert_bytes, key = _build_test_cert_and_key()
    payload = _make_signed_payload(
        private_key=key,
        cert_url="http://sns.eu-central-1.amazonaws.com/cert.pem",
    )
    with (
        patch.object(sns_validator, "_fetch_cert_bytes", return_value=cert_bytes),
        pytest.raises(sns_validator.SignatureError, match="https"),
    ):
        sns_validator.verify(payload)


# --- 2. SES envelope parser ---------------------------------------------------


def _ses_payload(
    *,
    sender: str,
    subject: str,
    body: str = "Hallo, ich habe ein Problem.\n",
    message_id: str = "<unique@gmail.com>",
    spam_status: str = "PASS",
    virus_status: str = "PASS",
    in_reply_to: str | None = None,
    references: str | None = None,
) -> str:
    """Build a JSON-encoded SES envelope as it would arrive in SNS.Message."""
    headers = [
        {"name": "From", "value": sender},
        {"name": "To", "value": "support@inbound.wagner-hausverwaltung.com"},
        {"name": "Subject", "value": subject},
        {"name": "Message-ID", "value": message_id},
    ]
    if in_reply_to:
        headers.append({"name": "In-Reply-To", "value": in_reply_to})
    if references:
        headers.append({"name": "References", "value": references})

    raw_mime = (
        f"From: {sender}\r\n"
        f"To: support@inbound.wagner-hausverwaltung.com\r\n"
        f"Subject: {subject}\r\n"
        f"Message-ID: {message_id}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n"
        f"\r\n"
        f"{body}"
    )
    inner = {
        "notificationType": "Received",
        "mail": {
            "messageId": "ses-msg-id",
            "source": sender,
            "destination": ["support@inbound.wagner-hausverwaltung.com"],
            "commonHeaders": {
                "from": [sender],
                "to": ["support@inbound.wagner-hausverwaltung.com"],
                "subject": subject,
                "messageId": message_id,
            },
            "headers": headers,
        },
        "receipt": {
            "spamVerdict": {"status": spam_status},
            "virusVerdict": {"status": virus_status},
        },
        "content": raw_mime,
    }
    return json.dumps(inner)


def test_extract_ticket_ref_finds_16_hex_chars() -> None:
    assert extract_ticket_ref("Re: [#0192837465fedcba] question") == "0192837465fedcba"
    assert extract_ticket_ref("[#AbCdEf12cafebabe] mixed case") == "abcdef12cafebabe"
    assert extract_ticket_ref("nothing special") is None
    assert extract_ticket_ref("[#xyz12345xyz12345] bad chars") is None  # non-hex letters
    assert extract_ticket_ref("[#01928374] only 8 chars") is None  # too short
    assert extract_ticket_ref("") is None


def test_parser_extracts_sender_subject_body() -> None:
    raw = _ses_payload(
        sender="alice@example.de",
        subject="Wasserschaden",
        body="Es tropft im Keller.\n",
    )
    parsed = parse_ses_sns_payload(raw)
    assert parsed.sender_email == "alice@example.de"
    assert parsed.subject == "Wasserschaden"
    assert "tropft" in parsed.body
    assert parsed.ticket_ref is None
    assert parsed.spam_pass is True
    assert parsed.virus_pass is True
    assert parsed.message_id == "<unique@gmail.com>"


def test_parser_extracts_ticket_ref_from_subject() -> None:
    raw = _ses_payload(
        sender="alice@example.de",
        subject="Re: [#deadbeefcafebabe] Frage",
    )
    parsed = parse_ses_sns_payload(raw)
    assert parsed.ticket_ref == "deadbeefcafebabe"


def test_parser_extracts_threading_headers() -> None:
    raw = _ses_payload(
        sender="alice@example.de",
        subject="Re: subject",
        in_reply_to="<orig-msg@server>",
        references="<orig-msg@server> <reply1@server>",
    )
    parsed = parse_ses_sns_payload(raw)
    assert parsed.in_reply_to == "<orig-msg@server>"
    assert parsed.references == "<orig-msg@server> <reply1@server>"


def test_parser_surfaces_spam_failure() -> None:
    raw = _ses_payload(
        sender="alice@example.de",
        subject="Buy bitcoin now",
        spam_status="FAIL",
    )
    parsed = parse_ses_sns_payload(raw)
    assert parsed.spam_pass is False
    assert parsed.virus_pass is True


def test_parser_handles_lowercase_normalises_sender() -> None:
    raw = _ses_payload(sender="Alice@Example.de", subject="x")
    parsed = parse_ses_sns_payload(raw)
    assert parsed.sender_email == "alice@example.de"


def test_parser_rejects_bad_notification_type() -> None:
    raw = json.dumps({"notificationType": "Bounce"})
    with pytest.raises(InboundEmailParseError):
        parse_ses_sns_payload(raw)


# --- 3. Webhook endpoint (signature verifier monkeypatched) -------------------


def _bypass_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the signature verifier a no-op for endpoint tests; we test signature
    behavior separately in the validator tests."""
    monkeypatch.setattr(
        "app.api.v1.webhooks.verify",
        lambda _msg: None,
    )


def _sns_envelope(message_body: str, msg_type: str = "Notification") -> dict[str, Any]:
    """SNS wrapper around a SES envelope. Signature field is present but unused
    (we bypass verify)."""
    return {
        "Type": msg_type,
        "MessageId": str(uuid.uuid4()),
        "Message": message_body,
        "Timestamp": datetime.now(UTC).isoformat(),
        "TopicArn": "arn:aws:sns:eu-central-1:271791846925:whv-email-inbound",
        "SigningCertURL": "https://sns.eu-central-1.amazonaws.com/cert.pem",
        "SignatureVersion": "2",
        "Signature": "sig",
    }


async def test_email_creates_new_ticket_for_unknown_sender(
    test_engine: AsyncEngine,
    stub_email: _StubEmailClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown sender → ticket gets external_sender_email; SES verdicts PASS;
    Verwalter gets notified."""
    _bypass_signature(monkeypatch)

    # Seed a verwalter so the fan-out has somewhere to land.
    # Note: must be in the WHV_ORGANIZATION_ID — the webhook hardcodes that.
    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    from app.auth.passwords import hash_password
    from app.models import Organization, User

    async with sm() as s:
        existing_org = await s.scalar(
            select(Organization).where(Organization.id == WHV_ORGANIZATION_ID)
        )
        if existing_org is None:
            s.add(Organization(id=WHV_ORGANIZATION_ID, name="WHV"))
            await s.commit()
        # Add a verwalter
        vw_email = f"vw-inbound-{uuid.uuid4().hex[:6]}@test.de"
        s.add(
            User(
                organization_id=WHV_ORGANIZATION_ID,
                email=vw_email,
                password_hash=hash_password("x"),
                role=UserRole.VERWALTER,
            )
        )
        await s.commit()

    envelope = _sns_envelope(
        _ses_payload(
            sender="stranger@example.de",
            subject="Heizung defekt",
            body="Bitte um Rückmeldung.",
            message_id=f"<{uuid.uuid4()}@gmail.com>",
        )
    )

    with TestClient(app) as client:
        r = client.post("/webhooks/email/inbound", json=envelope)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "created"

    # The ticket is persisted with external_sender_email + no creator user
    async with sm() as s:
        ticket = await s.scalar(select(Ticket).where(Ticket.id == uuid.UUID(body["ticket_id"])))
        assert ticket is not None
        assert ticket.created_by_user_id is None
        assert ticket.external_sender_email == "stranger@example.de"
        assert ticket.category == TicketCategory.SONSTIGES_OTHER
        assert ticket.status == TicketStatus.NEU
        assert ticket.subject == "Heizung defekt"

        message_rows = (
            await s.scalars(select(TicketMessage).where(TicketMessage.ticket_id == ticket.id))
        ).all()
        assert len(message_rows) == 1
        assert message_rows[0].source == TicketMessageSource.EMAIL
        assert message_rows[0].external_sender_email == "stranger@example.de"
        assert message_rows[0].author_user_id is None
        assert message_rows[0].email_message_id is not None

        # Audit row written
        audit = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "ticket_created_via_email",
                AuditLog.target_id == str(ticket.id),
            )
        )
        assert audit is not None

    # Verwalter got notified, threading headers were set
    assert len(stub_email.sent) == 1
    assert "stranger@example.de" not in stub_email.sent[0]["to"]
    assert "In-Reply-To" in stub_email.sent[0]["headers"]


async def test_email_appends_to_existing_ticket_via_ref(
    test_engine: AsyncEngine,
    stub_email: _StubEmailClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bypass_signature(monkeypatch)

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    from app.auth.passwords import hash_password
    from app.models import Organization, User

    async with sm() as s:
        existing_org = await s.scalar(
            select(Organization).where(Organization.id == WHV_ORGANIZATION_ID)
        )
        if existing_org is None:
            s.add(Organization(id=WHV_ORGANIZATION_ID, name="WHV"))
            await s.commit()

        # Pre-existing ticket
        creator_email = f"owner-{uuid.uuid4().hex[:6]}@test.de"
        creator = User(
            organization_id=WHV_ORGANIZATION_ID,
            email=creator_email,
            password_hash=hash_password("x"),
            role=UserRole.EIGENTUEMER,
        )
        s.add(creator)
        await s.flush()
        ticket = Ticket(
            organization_id=WHV_ORGANIZATION_ID,
            created_by_user_id=creator.id,
            category=TicketCategory.SCHADEN_ALLGEMEIN,
            status=TicketStatus.WARTET_AUF_KUNDE,
            subject="Original subject",
        )
        s.add(ticket)
        await s.commit()
        await s.refresh(ticket)
        ticket_id_str = str(ticket.id)

    # 16 hex chars (no dashes) — matches the production short_id format.
    short_id = uuid.UUID(ticket_id_str).hex[:16]
    envelope = _sns_envelope(
        _ses_payload(
            sender=creator_email,
            subject=f"Re: [#{short_id}] Original subject",
            body="Eine weitere Frage dazu.",
            message_id=f"<reply-{uuid.uuid4()}@gmail.com>",
        )
    )

    with TestClient(app) as client:
        r = client.post("/webhooks/email/inbound", json=envelope)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "appended"
    assert body["ticket_id"] == ticket_id_str

    async with sm() as s:
        msgs = (
            await s.scalars(
                select(TicketMessage)
                .where(TicketMessage.ticket_id == uuid.UUID(ticket_id_str))
                .order_by(TicketMessage.created_at)
            )
        ).all()
        assert len(msgs) == 1  # just the new reply (the original ticket had no messages)
        assert msgs[0].author_user_id is not None  # matched to creator
        assert msgs[0].source == TicketMessageSource.EMAIL

        # WARTET_AUF_KUNDE → OFFEN because owner replied
        refreshed = await s.scalar(select(Ticket).where(Ticket.id == uuid.UUID(ticket_id_str)))
        assert refreshed is not None
        assert refreshed.status == TicketStatus.OFFEN


async def test_email_idempotent_on_duplicate_message_id(
    test_engine: AsyncEngine,
    stub_email: _StubEmailClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bypass_signature(monkeypatch)

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    from app.models import Organization

    async with sm() as s:
        org_stmt = select(Organization).where(Organization.id == WHV_ORGANIZATION_ID)
        if await s.scalar(org_stmt) is None:
            s.add(Organization(id=WHV_ORGANIZATION_ID, name="WHV"))
            await s.commit()

    msg_id = f"<dup-{uuid.uuid4()}@gmail.com>"
    envelope = _sns_envelope(
        _ses_payload(sender="dup@example.de", subject="dup test", message_id=msg_id)
    )

    with TestClient(app) as client:
        r1 = client.post("/webhooks/email/inbound", json=envelope)
        assert r1.json()["status"] == "created"
        r2 = client.post("/webhooks/email/inbound", json=envelope)
        assert r2.json()["status"] == "duplicate"

    async with sm() as s:
        # Only one message inserted with that email_message_id
        msgs = (
            await s.scalars(select(TicketMessage).where(TicketMessage.email_message_id == msg_id))
        ).all()
        assert len(msgs) == 1


async def test_email_rejected_when_spam(
    test_engine: AsyncEngine,
    stub_email: _StubEmailClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bypass_signature(monkeypatch)
    from app.models import Organization

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        org_stmt = select(Organization).where(Organization.id == WHV_ORGANIZATION_ID)
        if await s.scalar(org_stmt) is None:
            s.add(Organization(id=WHV_ORGANIZATION_ID, name="WHV"))
            await s.commit()

    envelope = _sns_envelope(
        _ses_payload(
            sender="spammer@example.com",
            subject="Buy bitcoin",
            spam_status="FAIL",
        )
    )
    with TestClient(app) as client:
        r = client.post("/webhooks/email/inbound", json=envelope)
    assert r.json()["status"] == "rejected_spam_or_virus"
    # No outbound mail fired
    assert all("spammer" not in str(s["to"]) for s in stub_email.sent)


async def test_subscription_confirmation_visits_subscribe_url(
    monkeypatch: pytest.MonkeyPatch,
    stub_email: _StubEmailClient,
) -> None:
    """Patching `app.api.v1.webhooks.httpx.AsyncClient` is global (it mutates
    the shared httpx module object). EmailClient also uses httpx.AsyncClient,
    so the fake leaks into other DI paths in the same request. Two defences:
      - _FakeClient implements `aclose` so EmailClient.aclose() in the DI
        teardown doesn't raise AttributeError
      - stub_email fixture is required so EmailClient isn't actually
        instantiated (its __init__ would call the now-fake httpx.AsyncClient)
    """
    _bypass_signature(monkeypatch)
    _ = stub_email  # force fixture override of email_client BEFORE we patch httpx

    visited: list[str] = []

    class _FakeClient:
        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *_: Any) -> None:
            pass

        async def aclose(self) -> None:
            """Required for compatibility with EmailClient's DI teardown
            when the fake leaks via the global httpx module patch."""

        async def get(self, url: str) -> MagicMock:
            visited.append(url)
            resp = MagicMock()
            resp.status_code = 200
            return resp

    monkeypatch.setattr("app.api.v1.webhooks.httpx.AsyncClient", lambda **_: _FakeClient())

    envelope = _sns_envelope("", msg_type="SubscriptionConfirmation")
    envelope["SubscribeURL"] = (
        "https://sns.eu-central-1.amazonaws.com/?Action=ConfirmSubscription&Token=xyz"
    )

    with TestClient(app) as client:
        r = client.post("/webhooks/email/inbound", json=envelope)
    assert r.status_code == 200
    assert r.json()["status"] == "subscription_confirmed"
    assert visited == [
        "https://sns.eu-central-1.amazonaws.com/?Action=ConfirmSubscription&Token=xyz"
    ]


async def test_invalid_signature_rejected_with_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _always_fail(_msg: Any) -> None:
        raise sns_validator.SignatureError("bad")

    monkeypatch.setattr("app.api.v1.webhooks.verify", _always_fail)

    envelope = _sns_envelope(_ses_payload(sender="x@y.de", subject="x"))
    with TestClient(app) as client:
        r = client.post("/webhooks/email/inbound", json=envelope)
    assert r.status_code == 403


# --- 4. S3 path (SES "Save to S3 + notify SNS" action) -----------------------


def _ses_payload_s3(
    *,
    sender: str,
    subject: str,
    message_id: str = "<s3-test@gmail.com>",
    bucket: str = "whv-email-inbox",
    object_key: str = "abc123",
) -> str:
    """Build a SES envelope as it arrives when the rule uses the S3 action.

    Distinct from `_ses_payload` in that:
      - `content` is absent (the body lives at s3://{bucket}/{object_key})
      - `receipt.action.type == "S3"` with `bucketName` + `objectKey`
    """
    headers = [
        {"name": "From", "value": sender},
        {"name": "To", "value": "support@inbound.wagner-hausverwaltung.com"},
        {"name": "Subject", "value": subject},
        {"name": "Message-ID", "value": message_id},
    ]
    inner = {
        "notificationType": "Received",
        "mail": {
            "messageId": "ses-msg-id",
            "source": sender,
            "destination": ["support@inbound.wagner-hausverwaltung.com"],
            "commonHeaders": {
                "from": [sender],
                "to": ["support@inbound.wagner-hausverwaltung.com"],
                "subject": subject,
                "messageId": message_id,
            },
            "headers": headers,
        },
        "receipt": {
            "spamVerdict": {"status": "PASS"},
            "virusVerdict": {"status": "PASS"},
            "action": {
                "type": "S3",
                "bucketName": bucket,
                "objectKey": object_key,
            },
        },
    }
    return json.dumps(inner)


async def test_email_inbound_fetches_from_s3_when_no_inline_content(
    test_engine: AsyncEngine,
    stub_email: _StubEmailClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SES S3-action mode: webhook fetches raw MIME from S3 (mocked) instead
    of relying on inlined content. This is what makes large Outlook emails
    work."""
    _bypass_signature(monkeypatch)

    from app.auth.passwords import hash_password
    from app.models import Organization
    from app.models import User as UserModel

    sm = async_sessionmaker(test_engine, expire_on_commit=False)
    async with sm() as s:
        org_stmt = select(Organization).where(Organization.id == WHV_ORGANIZATION_ID)
        if await s.scalar(org_stmt) is None:
            s.add(Organization(id=WHV_ORGANIZATION_ID, name="WHV"))
            await s.commit()
        s.add(
            UserModel(
                organization_id=WHV_ORGANIZATION_ID,
                email=f"vw-s3-{uuid.uuid4().hex[:6]}@test.de",
                password_hash=hash_password("x"),
                role=UserRole.VERWALTER,
            )
        )
        await s.commit()

    # Mock the S3 fetch + delete — boto3 isn't called.
    raw_mime_in_s3 = (
        "From: sender@example.de\r\n"
        "To: support@inbound.wagner-hausverwaltung.com\r\n"
        "Subject: Großer Anhang dabei\r\n"
        "Message-ID: <s3-test-large@gmail.com>\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Das hier ist ein Body der in S3 liegt, nicht inline.\n"
    )
    fetched: list[tuple[str, str]] = []
    deleted: list[tuple[str, str]] = []

    async def _fake_fetch(_settings: Any, bucket: str, key: str) -> str:
        fetched.append((bucket, key))
        return raw_mime_in_s3

    async def _fake_delete(_settings: Any, bucket: str, key: str) -> None:
        deleted.append((bucket, key))

    monkeypatch.setattr("app.api.v1.webhooks.s3_fetch_raw_mime", _fake_fetch)
    monkeypatch.setattr("app.api.v1.webhooks.s3_delete_object", _fake_delete)

    envelope = _sns_envelope(
        _ses_payload_s3(
            sender="sender@example.de",
            subject="Großer Anhang dabei",
            message_id="<s3-test-large@gmail.com>",
            bucket="whv-email-inbox",
            object_key="2026/05/24/abc-def-123",
        )
    )

    with TestClient(app) as client:
        r = client.post("/webhooks/email/inbound", json=envelope)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "created"

    # S3 was consulted for the body + the object was cleaned up
    assert fetched == [("whv-email-inbox", "2026/05/24/abc-def-123")]
    assert deleted == [("whv-email-inbox", "2026/05/24/abc-def-123")]

    # The ticket has the body that came from S3, not from `content`
    async with sm() as s:
        ticket = await s.scalar(select(Ticket).where(Ticket.id == uuid.UUID(r.json()["ticket_id"])))
        assert ticket is not None
        msgs = (
            await s.scalars(select(TicketMessage).where(TicketMessage.ticket_id == ticket.id))
        ).all()
        assert len(msgs) == 1
        assert "Das hier ist ein Body der in S3 liegt" in msgs[0].body


# Keep make_org / make_user referenced so the imports aren't dropped by linter.
_ = make_org, make_user
