import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.contract import ContractType


class UnitContractSummary(BaseModel):
    """Denormalised "who's in this Einheit right now" — one row per
    currently-active contract on the unit (OWNER, TENANT, sometimes
    PROPERTY_OWNER on shared-area / WEG cases). `contact_label`
    is rendered server-side ("Max Mustermann" / "Acme GmbH") so
    clients don't reimplement the salutation / company-name logic.
    The `role` is whatever ContractContact carried (often empty);
    use `type` as the authoritative classifier."""

    contract_id: uuid.UUID
    contract_number: str | None = None
    type: ContractType
    contact_id: uuid.UUID | None = None
    contact_label: str | None = None
    role: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class UnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    impower_id: int | None = None
    unit_hr_id: str | None = None
    type: str
    floor: str | None = None
    position: str | None = None
    unit_rank: int | None = None
    is_owned_by_weg: bool | None = None
    voting_share: Decimal | None = None
    area_m2: Decimal | None = None
    heated_area_m2: Decimal | None = None
    persons: Decimal | None = None
    rooms: Decimal | None = None
    # Active contracts for this unit at request time. Empty when
    # the unit is vacant or has no contracts in the mirror.
    # PropertyDetail endpoint populates this; the bare /admin/units
    # list endpoint leaves it default-empty so the cheap-list
    # surface stays cheap.
    current_contracts: list[UnitContractSummary] = []
