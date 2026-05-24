import uuid

from pydantic import BaseModel, ConfigDict


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
