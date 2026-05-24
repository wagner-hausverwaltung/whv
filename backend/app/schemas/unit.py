import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


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
    rooms: Decimal | None = None
