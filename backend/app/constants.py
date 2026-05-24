import uuid
from typing import Final

# The single Wagner Hausverwaltung GmbH organization seeded by the initial
# Alembic migration. All domain rows in v1 carry this organization_id.
# See ADR-0002 for the single-tenant / multi-tenant-ready rationale.
WHV_ORGANIZATION_ID: Final[uuid.UUID] = uuid.UUID("01958d20-0000-7000-8000-000000005748")
