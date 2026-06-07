"""Shared Pydantic field types for API response schemas.

Pydantic v2 serialises ``Decimal`` to a JSON **string** (to preserve precision).
Our Swift/iOS clients decode money + area fields as ``Double``; a quoted string
makes ``decodeIfPresent(Double.self)`` *throw*, which silently empties whole
sections — the Dienstleister list, Mein Hausgeldkonto, the invoice-detail
dialog, the Mieter settlement, and the unit master table's MEA / area columns.

Serialise these as a JSON **number** instead. The JS portal already coerces
either form, so it is unaffected, and ``float`` carries ample precision for
euros and square metres. Use ``DecimalAsFloat`` for any Decimal that goes out
over the wire to a typed client. Validation/input is unchanged — the value
still parses and is stored as a ``Decimal``; only JSON serialisation differs.
"""

from decimal import Decimal
from typing import Annotated

from pydantic import PlainSerializer


def _decimal_to_float(value: Decimal) -> float:
    return float(value)


# A Decimal that serialises to a JSON number (not a string). None passes
# through untouched via the surrounding `| None` union.
DecimalAsFloat = Annotated[
    Decimal,
    PlainSerializer(_decimal_to_float, return_type=float, when_used="json"),
]
