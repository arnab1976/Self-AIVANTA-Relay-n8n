# Security, compliance and operations

| Control | Implementation |
|---|---|
| Enterprise SSO | `AUTH_MODE=oidc`: tokens are verified against JWKS (`security.py`); IdP groups map to roles through `ROLE_GROUP_MAP` |
| RBAC | `PERMISSIONS` matrix with a `require(perm)` dependency on every mutating endpoint |
| Tenant isolation | Every row carries `tenant_id`; `scoped_get` returns 404 for other tenants' rows; listing queries filter by tenant |
| Approval segregation | Only the designated role decides; requesters cannot approve their own commercial or final sign-off (`routers/approvals.py`) |
| Least-privilege tools | Tool registry scopes and per-tenant approval; agents only receive tools that are both permitted on the node and approved for the tenant |
| Upload safety | Allowed extensions, size limit, executable signature block and EICAR detection, optional ClamAV (`CLAMAV_HOST`) |
| PII redaction | Email, phone, PAN, Aadhaar, SSN and card numbers are redacted before storage and before any agent sees the text |
| Prompt-injection defence | RFP text is wrapped as `<untrusted_document>`; the guardrail prompt forbids following embedded instructions; tools and approvals cannot be changed by content |
| Secrets | Vault references only; validation rejects inline secrets; Terraform provisions Secret Manager |
| Runtime controls | Per-node timeouts and bounded retries, cancellation, idempotency keys for external actions, run worker isolation |
| Audit | Append-only, SHA-256 hash-chained events per tenant; `GET /api/audit` verifies the chain |
| Observability | Structured run events with trace IDs, tokens, latency and cost; add OpenTelemetry instrumentation (`opentelemetry-instrumentation-fastapi`) and Langfuse/LangSmith as needed |
| Retention | Bucket lifecycle rule (`retention_days`) in Terraform; add a scheduled purge for rows past retention |

## Operations

* **Scaling.** Set `RUN_EXECUTION=worker`, run `python -m aivanta_api.worker` replicas and use PostgreSQL. Workers claim runs with a conditional update.
* **Backups.** Turn on point-in-time recovery for PostgreSQL and versioning for the object bucket (both are on in Terraform).
* **Model failover.** Map profiles to a different provider per environment through `MODEL_*` variables.
* **Rollback.** Graph versions are immutable. To roll back, promote an earlier version or republish its content.
