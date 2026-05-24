"""SNS HTTP-subscription message signature verifier.

Verifies that a payload posted to our /webhooks/email/inbound endpoint
genuinely originated from AWS SNS. Per the AWS docs, the verifier:

  1. Refuses any message whose `SigningCertURL` host does not match a
     known AWS SNS pattern.
  2. Fetches the X.509 certificate from that URL (cached per URL).
  3. Builds the canonical "string to sign" from a fixed, ordered set of
     fields that depends on `Type` (Notification vs SubscriptionConfirmation
     vs UnsubscribeConfirmation).
  4. Verifies the base64-decoded `Signature` against that string using the
     algorithm declared in `SignatureVersion` (1 = SHA-1, 2 = SHA-256).

Without this, an attacker who knows our webhook URL could forge any "email
arrived" payload and create tickets at will. The verifier is the security
boundary.

We don't pull in a third-party SNS-validator package — the algorithm is
small enough to keep auditable here, and that dependency surface stays
zero.

Reference: https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message.html
"""

from __future__ import annotations

import base64
import re
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

# Permissive enough to match all AWS regions, strict enough to reject
# arbitrary domains. SNS publishes a cert at sns.<region>.amazonaws.com or
# sns.<region>.amazonaws.com.cn (China regions) — neither variant matters
# for WHV today but we accept both for completeness.
_SNS_HOST_RE = re.compile(r"^sns(\.[a-z0-9-]+)?\.amazonaws\.com(\.cn)?$")

# Fields used to build the canonical string, in the exact order AWS prescribes.
# Keys absent from a given message are simply skipped — but the documented
# canonical strings always include the entries listed here for the relevant
# Type, so absence indicates a malformed message and we treat it as invalid.
_NOTIFICATION_FIELDS = (
    "Message",
    "MessageId",
    "Subject",  # optional in the payload; only included when present
    "Timestamp",
    "TopicArn",
    "Type",
)
_SUBSCRIPTION_FIELDS = (
    "Message",
    "MessageId",
    "SubscribeURL",
    "Timestamp",
    "Token",
    "TopicArn",
    "Type",
)


class SignatureError(Exception):
    """Raised when an SNS payload fails verification.

    Caller MUST treat this as a hard 400 rejection — never process the
    message body further.
    """


def _check_host(signing_cert_url: str) -> None:
    parsed = urlparse(signing_cert_url)
    if parsed.scheme != "https":
        raise SignatureError("SigningCertURL must be https")
    if parsed.hostname is None or not _SNS_HOST_RE.match(parsed.hostname):
        raise SignatureError(f"SigningCertURL host not allowed: {parsed.hostname}")


@lru_cache(maxsize=64)
def _fetch_cert_bytes(signing_cert_url: str) -> bytes:
    """Fetches the SNS signing certificate. Cached aggressively — SNS rotates
    certs infrequently, and an attacker controlling the URL is blocked by
    the host-allowlist check above this layer."""
    response = httpx.get(signing_cert_url, timeout=10.0)
    response.raise_for_status()
    return response.content


def _canonical_string(message: dict[str, Any]) -> str:
    msg_type = message.get("Type")
    fields: tuple[str, ...]
    if msg_type == "Notification":
        fields = _NOTIFICATION_FIELDS
    elif msg_type in ("SubscriptionConfirmation", "UnsubscribeConfirmation"):
        fields = _SUBSCRIPTION_FIELDS
    else:
        raise SignatureError(f"Unknown SNS message Type: {msg_type!r}")

    parts: list[str] = []
    for field in fields:
        if field == "Subject" and field not in message:
            # Subject is optional for Notification; skip it cleanly when absent.
            continue
        if field not in message:
            raise SignatureError(f"Missing required field: {field}")
        parts.append(field)
        parts.append(str(message[field]))
    # Per AWS: each field on its own line, terminated by '\n'; final '\n'
    # included so the canonical string is byte-identical to what AWS signed.
    return "\n".join(parts) + "\n"


def _hash_algorithm(signature_version: str) -> hashes.HashAlgorithm:
    # SignatureVersion 1 = SHA-1 (legacy, still in use), 2 = SHA-256 (newer
    # topics; AWS recommends 2 for new topics). Accept both.
    if signature_version == "1":
        return hashes.SHA1()
    if signature_version == "2":
        return hashes.SHA256()
    raise SignatureError(f"Unsupported SignatureVersion: {signature_version}")


def verify(message: dict[str, Any]) -> None:
    """Verify the signature of an SNS payload.

    Raises `SignatureError` on any failure; returns silently on success.
    Caller passes the parsed JSON body as `message`.
    """
    signing_cert_url = message.get("SigningCertURL") or message.get("SigningCertUrl")
    if not signing_cert_url:
        raise SignatureError("Missing SigningCertURL")
    _check_host(signing_cert_url)

    sig_b64 = message.get("Signature")
    if not sig_b64:
        raise SignatureError("Missing Signature")

    try:
        signature = base64.b64decode(sig_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise SignatureError("Signature is not valid base64") from exc

    canonical = _canonical_string(message)
    cert_bytes = _fetch_cert_bytes(signing_cert_url)
    cert = x509.load_pem_x509_certificate(cert_bytes)
    public_key = cert.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise SignatureError("SNS cert public key is not RSA")

    hash_alg = _hash_algorithm(message.get("SignatureVersion", "1"))

    try:
        public_key.verify(
            signature,
            canonical.encode("utf-8"),
            padding.PKCS1v15(),
            hash_alg,
        )
    except InvalidSignature as exc:
        raise SignatureError("Signature does not match payload") from exc
