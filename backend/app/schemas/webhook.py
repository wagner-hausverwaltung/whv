from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ImpowerEntityType = Literal[
    "properties",
    "buildings",
    "units",
    "contracts",
    "contacts",
    "messages",
    "invoices",
    "documents",
]

ImpowerEventType = Literal["CREATE", "UPDATE", "DELETE"]


class ImpowerWebhookPayload(BaseModel):
    """Shape Impower sends on webhook delivery.

    Per https://api.app.impower.de/v2/docs §"Webhooks / Connections":

      POST <your.webhook.url>
      Authorization: Bearer TOKEN
      { "connectionId": 0, "entityType": "...", "entityId": 0, "eventType": "CREATE|UPDATE|DELETE" }
    """

    model_config = ConfigDict(populate_by_name=True)

    connection_id: int = Field(alias="connectionId")
    entity_type: ImpowerEntityType = Field(alias="entityType")
    entity_id: int = Field(alias="entityId")
    event_type: ImpowerEventType = Field(alias="eventType")
