# ADR-0002: Single-tenant deployment, multi-tenant-ready schemas

- Date: 2026-05-24
- Status: Accepted

## Context

`REQUIREMENTS.md` §14 Decision D5 defaults to "Single GmbH now, multi-tenant-ready schemas." Wagner Hausverwaltung GmbH (2026-05-24) confirmed it is the only company that will use the platform for the foreseeable future, but the spec calls for forward-compatible data modeling so an eventual second tenant doesn't require a destructive migration.

## Decision

V1 ships as a **single-tenant** deployment serving WHV only. No tenant-selection UI, no per-tenant config layer, no per-tenant secrets — those would be premature.

However, every table that would partition by tenant in a multi-tenant world carries an `organization_id` column from the first migration onward:

- An `organizations` table is created in the initial migration and seeded with one row for WHV (`name = "Wagner Hausverwaltung GmbH"`)
- Domain tables (`properties`, `units`, `contracts`, `contacts`, `documents`, `tickets`, `letters`, `circular_resolutions`, …) carry `organization_id NOT NULL REFERENCES organizations(id)`
- Composite indexes lead with `organization_id` where it materially helps query plans
- Service code reads `organization_id` from the authenticated user's context (`User.organization_id`), never from request bodies

Explicitly **out of scope** for v1:

- Tenant-scoped subdomains / routing
- Per-tenant feature flags
- Postgres row-level security (deferred until a real second tenant exists)
- Tenant-scoped object-storage prefixes (single bucket for now)

## Consequences

- A future migration to true multi-tenancy means adding tenant onboarding, scoping middleware, and (probably) RLS — but schema migrations are minimized to backfills and constraint adjustments, not column additions
- Marginal storage overhead per row (one UUID column + one index entry) for v1
- Forces developers to think about tenant scoping from day one — caught early
