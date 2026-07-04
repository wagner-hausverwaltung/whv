"""Schemas for Versorgungsverträge (supplier contracts, Verwalter-only)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models import SupplierContractCategory, SupplierContractPricePeriod


class SupplierContractBody(BaseModel):
    """Create/update payload — PUT replaces the full metadata set."""

    category: str
    provider_name: str = Field(min_length=1, max_length=200)
    contact_id: uuid.UUID | None = None
    contract_number: str | None = Field(default=None, max_length=100)
    customer_number: str | None = Field(default=None, max_length=100)
    meter_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    cancellation_months: int | None = Field(default=None, ge=0, le=60)
    auto_renew: bool | None = None
    price: Decimal | None = Field(default=None, ge=0, le=Decimal("99999999.99"))
    price_period: str | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("category")
    @classmethod
    def _category_known(cls, v: str) -> str:
        if v not in SupplierContractCategory:
            raise ValueError(f"unknown category {v!r}")
        return v

    @field_validator("price_period")
    @classmethod
    def _period_known(cls, v: str | None) -> str | None:
        if v is not None and v not in SupplierContractPricePeriod:
            raise ValueError(f"unknown price_period {v!r}")
        return v


class SupplierContractResponse(BaseModel):
    id: uuid.UUID
    property_id: uuid.UUID
    # Display conveniences for the cross-property board / meter link.
    property_name: str | None = None
    meter_number: str | None = None
    category: str
    provider_name: str
    contact_id: uuid.UUID | None
    contract_number: str | None
    customer_number: str | None
    meter_id: uuid.UUID | None
    start_date: date | None
    end_date: date | None
    cancellation_months: int | None
    auto_renew: bool | None
    price: Decimal | None
    price_period: str | None
    notes: str | None

    model_config = {"from_attributes": True}
