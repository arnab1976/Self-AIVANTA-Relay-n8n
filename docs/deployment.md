# Deployment

## Topology

```
                 public HTTPS (WAF)                       private network only
Users ──► web ──► /api/* ──► api ──────────────────────────► n8n main (public API, webhooks, editor*)
                              ▲  ▲                                   │  Redis queue
                              │  └── /gateway/v1  ◄── n8n workers ◄──┘
                              └───── /internal/n8n ◄── (HTTP Request + AI Agent nodes)
          worker ──► waits on n8n executions, resumes approvals, retries        * editor: platform team via VPN / IAP
```

| Container | Scale | Notes |
|---|---|---|
| `api` | 2+ | Serves the portal API **and** the bridge; stateless |
| `worker` | 2+ | `RUN_EXECUTION=worker`: claims runs, triggers n8n, waits, resumes |
| `web` | 2+ | Next.js standalone |
| `n8n` (main) | 1 | Editor, public API, webhooks; `EXECUTIONS_MODE=queue` |
| `n8n-worker` | 1–N | `n8n worker`; scale on Redis queue depth |

## Required settings

| Setting | Where | Value |
|---|---|---|
| `AIVANTA_BRIDGE_TOKEN` | api, worker | Long random secret; also stored in the two n8n credentials |
| `AIVANTA_BRIDGE_URL` | api, worker | Internal URL n8n uses to reach the API, e.g. `http://api:8000` |
| `N8N_MODE=rest`, `N8N_API_URL`, `N8N_WEBHOOK_URL`, `N8N_API_KEY` | api, worker | Internal n8n URLs; API key from `scripts/n8n_bootstrap.py` |
| `WEBHOOK_URL` | n8n main + workers | **Internal** n8n URL, so `$execution.resumeUrl` is reachable from the API |
| `N8N_ENCRYPTION_KEY` | n8n main + workers | Same value everywhere; back it up |
| `EXECUTIONS_DATA_PRUNE` / `EXECUTIONS_DATA_MAX_AGE` | n8n | Execution retention; AIVANTA keeps its own run history |
| `NODES_EXCLUDE` | n8n | Disables Execute Command, SSH and file access nodes |

## Clouds

`infra/terraform/aws` (ECS Fargate, RDS, ElastiCache, S3, Secrets Manager), `infra/terraform/azure` (Container Apps, PostgreSQL Flexible Server, Azure Cache for Redis, Blob, Key Vault) and `infra/terraform/gcp` (Cloud Run, Cloud SQL, Memorystore, Cloud Storage, Secret Manager). See `infra/terraform/README.md` for the post-apply steps.

## Operations

* **Upgrading n8n.** Pin `N8N_IMAGE_TAG`. Run `pytest tests/unit` (compiler output) and `tests/live` against a staging n8n before rolling production.
* **Backups.** Back up both databases. The n8n database can be recreated by republishing, but executions and credentials live there.
* **Observability.** Correlate AIVANTA run id ⇄ n8n execution id (both are on the run page). Ship n8n logs and AIVANTA logs to the same place.
* **Rotation.** To rotate the bridge token: set the new value, delete `N8N_CREDENTIALS_CACHE`, delete the two n8n credentials and restart `api`. They are recreated, and new workflows reference the new credential ids; republish canvases to move existing workflows.
