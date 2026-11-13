# Multi-tenancy in AIVANTA Relay

## Layers

| Layer | Isolation |
|---|---|
| Identity | One identity per tenant user (OIDC claim `aivanta_tenant`, groups → roles). Provider Admins are a separate identity class (`aivanta-provider`). |
| Data | Every AIVANTA row carries `tenant_id`, and every query is scoped by it. Plans choose RLS (Starter), schema per tenant (Growth) or a dedicated database (Enterprise). |
| Objects | Stored under `objects/<tenant>/<project>/…`, in a per-tenant prefix or bucket. |
| Policy | Per tenant: model allowlist, tool approvals, integrations, rate card, margin floor, discount limit, FX. |
| n8n | Shared instance by default: workflows are named and tagged per tenant and carry no tenant data. Enterprise tenants can have a dedicated n8n (`N8N_TENANT_INSTANCES`). Tenants never sign in to n8n. |
| Audit | A hash-chained audit trail per tenant; provider actions are recorded in the affected tenant's chain. |

## Onboarding flows

```
Request Access (public)
   ├── join an existing tenant  ──► Tenant Admin approves  ──► user created with the requested role
   └── new organisation         ──► Provider Admin approves ──► tenant provisioned:
                                         plan → isolation model + n8n placement,
                                         cloud + region, currency, first Tenant Admin,
                                         starter project + RFP-to-SOW canvas
```

* Provider Admins can also provision directly, change plans, and suspend or reactivate tenants. A suspended tenant's tokens are refused on every `/api` route except sign-in.
* Tenant Admins manage users and roles, join requests, the model allowlist and integrations.

## Why the bridge matters for tenancy

Because each n8n step calls back into AIVANTA with only `run_id`, `node_id` and the execution id, the tenant is always resolved server-side from the run record. A workflow cannot reach another tenant's data even if someone edits it in n8n, and policy changes apply immediately.
