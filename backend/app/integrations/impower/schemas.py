"""Public re-exports of the Impower DTOs we mirror.

The underlying types live in `_schemas_generated.py`, which is produced by
`datamodel-code-generator` from the converted OpenAPI 3 spec. Treat the
generated file as read-only — see ADR-0003 for the regeneration command.
"""

from app.integrations.impower._schemas_generated import (
    ContactBankDetailsDto,
    ContactDetailsDto,
    ContactDto,
    ContactSimpleDto,
    ContractDto,
    PageOfUnitDto,
    PropertyAddressDto,
    PropertyDto,
    SliceOfContactDto,
    SliceOfContractDto,
    SliceOfPropertyDto,
    UnitDto,
)

__all__ = [
    "ContactBankDetailsDto",
    "ContactDetailsDto",
    "ContactDto",
    "ContactSimpleDto",
    "ContractDto",
    "PageOfUnitDto",
    "PropertyAddressDto",
    "PropertyDto",
    "SliceOfContactDto",
    "SliceOfContractDto",
    "SliceOfPropertyDto",
    "UnitDto",
]
