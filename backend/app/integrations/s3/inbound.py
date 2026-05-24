"""S3 fetcher for inbound emails.

When the SES receipt rule uses the **S3 action with SNS notification**, the
SES → SNS payload's `Message` JSON does NOT contain the email body. Instead,
the body lives at `s3://{bucket}/{objectKey}` and the notification carries
the bucket + key reference. This module fetches the body.

Why S3 instead of the simpler "Publish to SNS" action: the SNS publish path
caps the inlined email content at 150 KB. Any real-world Outlook email (HTML
signature, embedded company logo) blows past that and SES drops the message.
With S3, there's no upper bound.

boto3 is sync; we call it via `asyncio.to_thread` so the FastAPI event loop
stays responsive.

After successful processing, the caller should `delete_object` to keep the
bucket from accumulating PII indefinitely. (A lifecycle rule on the bucket
is a belt-and-braces defence.)
"""

from __future__ import annotations

import asyncio
import contextlib

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.config import Settings


class S3FetchError(Exception):
    """Raised when an inbound email's body cannot be retrieved from S3."""


def _build_client(settings: Settings):  # type: ignore[no-untyped-def]
    """Build a boto3 S3 client with explicit creds + region.

    Not cached at module level because `get_settings()` is cached but `Settings`
    is a plain dataclass — instantiating a client per call is cheap (~ms).
    """
    if not settings.aws_access_key_id or not settings.aws_secret_access_key:
        raise S3FetchError("AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY not configured")
    return boto3.client(
        "s3",
        region_name=settings.s3_inbound_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        # Short timeouts — if S3 hangs, our webhook should fail fast and
        # let SNS retry rather than block the event loop for minutes.
        config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 3}),
    )


def _fetch_sync(settings: Settings, bucket: str, key: str) -> str:
    client = _build_client(settings)
    try:
        obj = client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        raise S3FetchError(f"S3 GET failed for {bucket}/{key}: {exc}") from exc
    body_bytes = obj["Body"].read()
    # SES stores raw RFC 5322 text; ASCII-compatible UTF-8 in nearly all
    # real-world cases. Use replacement on decode errors so we never lose
    # the whole message because of one bad byte (typical for forwarded mail
    # from older clients).
    text: str = body_bytes.decode("utf-8", errors="replace")
    return text


def _delete_sync(settings: Settings, bucket: str, key: str) -> None:
    client = _build_client(settings)
    # Best-effort cleanup — if the delete fails we'd rather not raise and
    # rollback the ticket that just got created. The bucket lifecycle rule
    # will purge stragglers within the retention window.
    with contextlib.suppress(ClientError):
        client.delete_object(Bucket=bucket, Key=key)


async def fetch_raw_mime(settings: Settings, bucket: str, key: str) -> str:
    """Fetch the raw MIME body of an inbound email from S3."""
    return await asyncio.to_thread(_fetch_sync, settings, bucket, key)


async def delete_object(settings: Settings, bucket: str, key: str) -> None:
    """Best-effort delete after a ticket has been successfully ingested."""
    await asyncio.to_thread(_delete_sync, settings, bucket, key)
