# ADR-0004: Tenant-aware entities from day one

**Status:** Accepted

**Decision.** Every table carries `tenant_id`, and every query is scoped to the caller's tenant (`scoped_get`, filtered listings). Tenants record their isolation model (schema per tenant, dedicated database or row-level security) as metadata. The reference implementation enforces isolation in the application layer. Deployments needing a stronger guarantee add PostgreSQL row-level security policies keyed on `tenant_id`, or deploy one database per tenant.

**Consequences.** Multi-tenant billing and isolation certification are deferred, as the blueprint recommends, without a later data migration.
