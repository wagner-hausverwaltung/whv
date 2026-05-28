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

    # ---- Connections (webhook registration) ----------------------------------
    # Impower's `/v2/connections` API is how third-party apps subscribe to
    # entity-change events. We register one connection per environment
    # (staging + prod) pointing at `/webhooks/impower`; Impower then POSTs
    # to that URL whenever a property / unit / contract / contact / document
    # changes.
    #
    # The `decryptedSecret` we provide here is what Impower uses to sign
    # subsequent webhook deliveries (HMAC-SHA256 of the body, sent in the
    # `X-Impower-Signature` header). Must match what we configure on our
    # side as `IMPOWER_WEBHOOK_SECRET`.

    async def register_connection(
        self,
        *,
        webhook_url: str,
        secret: str,
        name: str | None = None,
        app_id: int = 8,
    ) -> dict[str, Any]:
        """POST /v2/connections — register a new webhook subscriber.

        Returns the raw JSON Impower replied with (includes the new
        connection id + state). We don't bind it to the generated
        ConnectionDto because the CLI just prints the result + doesn't
        need typed access.
        """
        payload = {
            "appId": app_id,
            "decryptedSecret": secret,
            "webhookUrl": webhook_url,
        }
        if name is not None:
            payload["name"] = name
        response = await self._request("POST", "/v2/connections", json=payload)
        result: dict[str, Any] = response.json()
        return result

    async def list_connections(self) -> list[dict[str, Any]]:
        """GET /v2/connections — every connection registered for the
        caller's tenant. Used by the CLI's `webhook list` command to
        confirm a registration landed."""
        response = await self._request("GET", "/v2/connections")
        data = response.json()
        if isinstance(data, list):
            return data
        # Some Impower endpoints wrap collections in {"content": […]}; be
        # defensive in case this one does too.
        content = data.get("content")
        if isinstance(content, list):
            return content
        return []

    async def delete_connection(self, connection_id: int, *, delete_related: bool = True) -> None:
        """DELETE /v2/connections/{id} — remove a registered subscriber.
        `delete_related=True` (default per Impower spec) also cleans up
        any state the connection's app provisioned."""
        await self._request(
            "DELETE",
            f"/v2/connections/{connection_id}",
            json={"deleteRelated": delete_related},
        )

    async def list_properties(
        self, page: int = 0, size: int = _DEFAULT_PAGE_SIZE
    ) -> SliceOfPropertyDto:
        response = await self._request("GET", "/properties", params={"page": page, "size": size})
        return SliceOfPropertyDto.model_validate(response.json())

    async def get_invoice(self, invoice_id: int) -> dict[str, Any]:
        """GET /v2/invoices/{id} — returns the structured invoice with
        line items (`items`), each carrying `accountCode`, `accountName`
        ("Passive Rechnungsabgrenzungsposten"), `amount`, `bookingText`
        ("Strom Lieferung 15.04.2025 - 31.12.2025"), `vatAmount`,
        `vatPercentage`.

        Used by `/me/properties/{id}/invoices/{source_id}` to surface
        the Buchungsdetails in the Dienstleister-tab invoice dialog.
        Returned as a raw dict because the generated `InvoiceDto`
        nests a dozen unrelated fields the SPA doesn't render; the
        endpoint shapes a narrow `InvoiceDetailResponse` instead.
        """
        response = await self._request("GET", f"/invoices/{invoice_id}")
        result: dict[str, Any] = response.json()
        return result

    async def get_accounts(
        self,
        *,
        property_id: int,
        source_ids: list[int] | None = None,
        source_types: list[str] | None = None,
        page: int = 0,
        size: int = _DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """GET /v2/accounts — chart-of-accounts entries for a property.

        Filter by `source_ids` (a contact id for sourceType=CONTACT, a
        contract id for CONTRACT) + `source_types` to land on a single
        owner's Hausgeld (Debitoren) account. Returns the raw paged
        body; the caller pulls `content`.
        """
        params: dict[str, Any] = {"page": page, "size": size, "propertyIds": [property_id]}
        if source_ids:
            params["sourceIds"] = source_ids
        if source_types:
            params["accountSourceTypes"] = source_types
        response = await self._request("GET", "/accounts", params=params)
        result: dict[str, Any] = response.json()
        return result

    async def get_posting_items(
        self,
        *,
        account_ids: list[int],
        page: int = 0,
        size: int = _DEFAULT_PAGE_SIZE,
        sort: str = "postDate",
        order: str = "DESC",
    ) -> dict[str, Any]:
        """GET /v2/posting-items — bookings on the given account(s),
        newest first. Returns the raw paged body (`content`)."""
        params: dict[str, Any] = {
            "page": page,
            "size": size,
            "accountIds": account_ids,
            "sort": sort,
            "order": order,
        }
        response = await self._request("GET", "/posting-items", params=params)
        result: dict[str, Any] = response.json()
        return result

    async def get_rent_settlements(
        self,
        *,
        contract_ids: list[int],
        page: int = 0,
        size: int = _DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """GET /v2/rent-settlement — the MV-property owner's payout
        statements (Mietabrechnung) for the given owner contract(s):
        rentIncomeAmount, payoutAmount, balanceAmount, timeframe,
        dueDate. Filtered by the caller's own contract ids so a tenant
        / other owner never sees someone else's. Raw paged body."""
        params: dict[str, Any] = {
            "page": page,
            "size": size,
            "contractIds": contract_ids,
            "sort": "dueDate",
            "order": "DESC",
        }
        response = await self._request("GET", "/rent-settlement", params=params)
        result: dict[str, Any] = response.json()
        return result

    async def get_plan_adjustment_suggestions(
        self,
        *,
        contract_id: int,
        page: int = 0,
        size: int = _DEFAULT_PAGE_SIZE,
    ) -> dict[str, Any]:
        """GET /v2/plan-adjustments/suggestions for one contract —
        proposed Hausgeld adjustments (previousCost, amount, targetDate,
        ownerCommunicationState). Filtered per contract because the
        suggestion body itself carries no contract/property id. Returns
        the raw paged body (`content`)."""
        params: dict[str, Any] = {"page": page, "size": size, "contractId": contract_id}
        response = await self._request("GET", "/plan-adjustments/suggestions", params=params)
        result: dict[str, Any] = response.json()
        return result

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
        response = await self._client.request("GET", f"/documents/{document_id}/download")
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
