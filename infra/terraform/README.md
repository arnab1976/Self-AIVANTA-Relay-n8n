# Infrastructure

Terraform starting points for running AIVANTA Relay on any of the three clouds. Each deploys the same five containers:
`api`, `worker`, `web`, `n8n` (main: editor, public API, webhooks) and `n8n-worker` (queue mode, scale horizontally).

| Concern | AWS (`aws/`) | Azure (`azure/`) | GCP (`gcp/`) |
|---|---|---|---|
| Containers | ECS Fargate + Cloud Map private DNS | Container Apps (VNet-integrated) | Cloud Run (VPC access) |
| AIVANTA + n8n databases | RDS for PostgreSQL 16 | PostgreSQL Flexible Server 16 (`VECTOR` extension) | Cloud SQL for PostgreSQL 16 (`pgvector`) |
| n8n queue | ElastiCache for Redis | Azure Cache for Redis | Memorystore for Redis |
| Objects (RFPs, artifacts) | S3 (KMS, versioned) | Blob Storage (versioned) | Cloud Storage (versioned) |
| Secrets | Secrets Manager | Key Vault / Container Apps secrets | Secret Manager |
| Images | ECR | Azure Container Registry | Artifact Registry |
| Edge | ALB (HTTPS) — web and `/api/*` only | Front Door / App Gateway with WAF | External HTTPS LB + Cloud Armor + IAP |

## Network rules that matter

* **Public:** the web app and `/api/*` only.
* **Private (n8n → API):** `/internal/n8n/*` (bridge) and `/gateway/v1/*` (model gateway). Never route them through the public edge.
* **Private (API → n8n):** n8n public API (`/api/v1`), webhooks (`/webhook/*`) and resume URLs (`/webhook-waiting/*`).
  Set n8n's `WEBHOOK_URL` to the *internal* n8n URL so resume URLs are reachable from the API.
* **The n8n editor** is for the platform team only: VPN, AWS Verified Access, Azure Private Link or GCP IAP. Tenants never sign in to n8n.

## After `terraform apply`

1. Create the n8n database role if your module does not (`CREATE ROLE n8n …; CREATE DATABASE n8n OWNER n8n;`).
2. Run `python scripts/n8n_bootstrap.py --n8n <internal n8n url> --email … --password …` from a bastion or a one-off task. Store the printed key as `N8N_API_KEY` in the secrets service.
3. Restart `api` and `worker`. On start-up the API creates the *AIVANTA Bridge* and *AIVANTA Model Gateway* credentials in n8n.
4. Build and push `infra/docker/api.Dockerfile` and `infra/docker/web.Dockerfile` images, then roll the services.

These modules are deliberately compact starting points. Add your organisation's VPC, DNS, WAF, backup, monitoring and tagging standards before production.
