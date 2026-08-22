import uuid

from pydantic import BaseModel, ConfigDict

from app.schemas.types import DecimalAsFloat
from app.schemas.unit import UnitResponse


class PropertyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    impower_id: int | None = None
    property_hr_id: str | None = None
    name: str
    type: str
    state: str
    city: str | None = None
    street: str | None = None
    number: str | None = None
    postal_code: str | None = None
    country: str | None = None
    # Emitted as JSON numbers (not Decimal→string): the iOS client decodes Double.
    lat: DecimalAsFloat | None = None
    lng: DecimalAsFloat | None = None
    # Verwalter-uploaded hero photo URL (relative — caller prepends API
    # base). None until the admin uploads one; the portal property list
    # falls back to a neutral placeholder card.
    image_url: str | None = None


class PropertyDetailResponse(PropertyResponse):
    units: list[UnitResponse] = []
