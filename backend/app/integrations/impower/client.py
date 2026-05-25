import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx
from fastapi import Depends

from app.config import Settings, get_settings
from app.integrations.impower.schemas import (
    ContactDto,
    ContractDto,
    DocumentDto,
    PageOfDocumentDto,
    PageOfUnitDto,
    PropertyDto,
    SliceOfContactDto,
    SliceOfContractDto,
    SliceOfPropertyDto,
    UnitDto,
)

_DEFAULT_PAGE_SIZE = 100
_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 1.0


class ImpowerError(Exception):
    pass


class ImpowerClient:
    """Async client for Impower's REST API.

    Handles bearer auth, exponential-backoff retry on 5xx and connection
    errors, and respects 429 Retry-After headers. Pagination helpers iterate
    transparently over Slice/Page responses.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ImpowerClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.request(method, path, **kwargs)
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                last_exc = exc
                if attempt == _MAX_RETRIES - 1:
                    raise ImpowerError(f"{method} {path} failed: {exc}") from exc
                await asyncio.sleep(_BASE_BACKOFF_SECONDS * (2**attempt))
                continue

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "1"))
                if attempt == _MAX_RETRIES - 1:
                    raise ImpowerError(
                        f"{method} {path} rate-limited after {_MAX_RETRIES} attempts"
                    )
                await asyncio.sleep(retry_after)
                continue

            if 500 <= response.status_code < 600:
                if attempt == _MAX_RETRIES - 1:
                    raise ImpowerError(
                        f"{method} {path} returned {response.status_code}: {response.text[:200]}"
                    )
                await asyncio.sleep(_BASE_BACKOFF_SECONDS * (2**attempt))
                continue

            if response.status_code >= 400:
                raise ImpowerError(
                    f"{method} {path} returned {response.status_code}: {response.text[:200]}"
                )

            return response

        raise ImpowerError(f"{method} {path} exhausted retries") from last_exc

    async def list_properties(
        self, page: int = 0, size: int = _DEFAULT_PAGE_SIZE
    ) -> SliceOfPropertyDto:
        response = await self._request("GET", "/properties", params={"page": page, "size": size})
        return SliceOfPropertyDto.model_validate(response.json())

    async def list_units(
        self,
        page: int = 0,
        size: int = _DEFAULT_PAGE_SIZE,
        property_id: int | None = None,
    ) -> PageOfUnitDto:
        params: dict[str, Any] = {"page": page, "size": size}
        if property_id is not None:
            params["propertyId"] = property_id
        response = await self._request("GET", "/units", params=params)
        return PageOfUnitDto.model_validate(response.json())

    async def list_contracts(
        self,
        page: int = 0,
        size: int = _DEFAULT_PAGE_SIZE,
        property_id: int | None = None,
    ) -> SliceOfContractDto:
        params: dict[str, Any] = {"page": page, "size": size}
        if property_id is not None:
            params["propertyId"] = property_id
        response = await self._request("GET", "/contracts", params=params)
        return SliceOfContractDto.model_validate(response.json())

    async def list_contacts(
        self, page: int = 0, size: int = _DEFAULT_PAGE_SIZE
    ) -> SliceOfContactDto:
        response = await self._request("GET", "/contacts", params={"page": page, "size": size})
        return SliceOfContactDto.model_validate(response.json())

    async def list_documents(
        self,
        page: int = 0,
        size: int = _DEFAULT_PAGE_SIZE,
        property_id: int | None = None,
    ) -> PageOfDocumentDto:
        params: dict[str, Any] = {"page": page, "size": size}
        if property_id is not None:
            params["propertyId"] = property_id
        response = await self._request("GET", "/documents", params=params)
        return PageOfDocumentDto.model_validate(response.json())

    async def iter_properties(self) -> AsyncIterator[PropertyDto]:
        page = 0
        while True:
            slice_ = await self.list_properties(page=page)
            content = slice_.content or []
            if not content:
                return
            for prop in content:
                yield prop
            page += 1

    async def iter_units(self, property_id: int | None = None) -> AsyncIterator[UnitDto]:
        page = 0
        while True:
            page_obj = await self.list_units(page=page, property_id=property_id)
            content = page_obj.content or []
            if not content:
                return
            for unit in content:
                yield unit
            page += 1

    async def iter_contracts(self, property_id: int | None = None) -> AsyncIterator[ContractDto]:
        page = 0
        while True:
            slice_ = await self.list_contracts(page=page, property_id=property_id)
            content = slice_.content or []
            if not content:
                return
            for contract in content:
                yield contract
            page += 1

    async def iter_contacts(self) -> AsyncIterator[ContactDto]:
        page = 0
        while True:
            slice_ = await self.list_contacts(page=page)
            content = slice_.content or []
            if not content:
                return
            for contact in content:
                yield contact
            page += 1

    async def iter_documents(self, property_id: int) -> AsyncIterator[DocumentDto]:
        """Iterate documents for a single property.

        property_id is required: Impower's /v2/documents without a property
        filter times out (likely returns the entire customer's catalog).
        """
        page = 0
        while True:
            page_obj = await self.list_documents(page=page, property_id=property_id)
            content = page_obj.content or []
            if not content:
                return
            for doc in content:
                yield doc
            page += 1

    async def download_document_content(self, document_id: int) -> bytes | None:
        """Fetch the raw bytes for one Impower document.

        Endpoint: `GET /documents/{id}/download`. Used by the LLM
        extraction pipeline to source invitation PDFs that haven't been
        mirrored locally yet (§1.4d iter 2 will eventually cache them
        in Hetzner OS — until then we hit Impower on demand).

        Returns None when Impower says "no file" — either 404 with
        "File is not available" or 500 with "Cannot download file" /
        "File loading failed". The 500 case is what we mostly hit on
        the prod-replica: the document row exists but the PDF was
        never rendered (or has expired off Impower's blob store).
        Treating both as "no file" is correct because retrying won't
        materialise the file; recording "no_source_pdf" in the audit
        log is the right outcome.

        Bypasses the shared `_request()` retry+raise wrapper so we can
        inspect the body BEFORE the wrapper escalates 5xx into an
        ImpowerError — that wrapper exists for genuine server-side
        outages where retrying helps, and is wrong for this endpoint.
        """
        # Direct call: no retry, no auto-raise on 5xx. Network errors
        # still bubble up as httpx exceptions; the Celery wrapper
        # treats those as retryable.
        response = await self._client.request(
            "GET", f"/documents/{document_id}/download"
        )
        if response.status_code in (200, 201):
            return response.content
        if response.status_code in (404, 500):
            body_lower = response.text.lower()
            no_file_hints = (
                "cannot download",
                "file loading failed",
                "file is not available",
                "file couldn't be loaded",
                "file could not be loaded",
            )
            if any(h in body_lower for h in no_file_hints):
                return None
        # Anything else (real 5xx, auth, etc.) — let the Celery task
        # retry on it.
        response.raise_for_status()
        return response.content


async def get_impower_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[ImpowerClient]:
    """FastAPI dependency that yields an ImpowerClient bound to the configured token."""
    async with ImpowerClient(settings.impower_api_base, settings.impower_api_token) as client:
        yield client
