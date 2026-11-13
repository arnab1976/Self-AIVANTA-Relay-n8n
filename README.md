# AIVANTA Relay

**AIVANTA presales-to-delivery intelligence platform, built on n8n.**
*Every RFP becomes a workflow your whole bid team can see.*

AIVANTA turns customer RFPs into controlled requirements, BRDs, SOWs, architecture options, effort and cloud estimates, deterministic pricing and staffing plans. In **Relay**, every workflow you design on the AIVANTA canvas is compiled into an **n8n workflow** and executed by n8n: triggers, AI Agent nodes, routing, joins, retries and Send & Wait approvals. AIVANTA wraps n8n with what a commercial, multi-tenant product needs: tenants and subscriptions, roles and SSO, a model gateway with per-tenant allowlists, a governed tool gateway, deterministic pricing, versioned artifacts and a hash-chained audit trail.

```
 Browser ──► AIVANTA web (Next.js) ──► AIVANTA API (FastAPI) ──publish/run──► n8n public API + webhook
                                            ▲         ▲                              │  (queue mode: main + workers)
                                            │         └──── /gateway/v1 (OpenAI) ◄───┤  AI Agent → Chat Model node
                                            └────────────── /internal/n8n/{op} ◄─────┘  HTTP Request nodes (bridge)
```

| | |
|---|---|
| Orchestration | **n8n 2.x** (tested with n8n 2.45.7, Node 24) — self-hosted, queue mode, Postgres + Redis |
| AI agents | n8n **AI Agent** nodes with an **OpenAI Chat Model** sub-node pointed at the AIVANTA model gateway (`RELAY_AGENT_MODE=native`), or AIVANTA-executed agents (`service`) |
| Portal + API | Next.js 14 + React Flow canvas · FastAPI · SQLAlchemy 2 · PostgreSQL (pgvector) |
| Tenancy | Request Access → Tenant Admin / Provider Admin approval · plans · suspension · shared or dedicated n8n per tenant |
| Clouds | Docker Compose locally; Terraform for **AWS** (ECS Fargate), **Azure** (Container Apps) and **GCP** (Cloud Run) |

---

## Quick start (laptop, no n8n server, no API keys)

Requirements: Python 3.11+, Node 20+.

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                                   # SQLite, mock LLM, dev sign-in, N8N_MODE=emulated
uvicorn aivanta_api.main:app --reload --port 8000      # API + docs at http://localhost:8000/docs
npm install && npm run dev                             # web at http://localhost:3000 (second terminal)
```

`N8N_MODE=emulated` runs the **same compiled n8n workflow JSON** in an in-process interpreter (Webhook, HTTP Request, Switch, IF, Wait, Merge, AI Agent). It is for tests and demos only; real deployments use `N8N_MODE=rest`.

Open http://localhost:3000. The home page has **Request Access**, **Tenant Admin**, **Provider Admin** and **Start Journey**. Start a journey, pick a tenant and a role, open **Agent Canvas → RFP-to-SOW**, publish and run. Use **Export** on the canvas to see the n8n workflow JSON.

```bash
pytest -q             # 47 tests: compiler, bridge, gateway, onboarding, API flow and runtime contract (emulated n8n)
npm run build         # type-check and build the web app
```

## With a real n8n (Docker Compose)

```bash
cp .env.example .env                       # set AIVANTA_BRIDGE_TOKEN and N8N_ENCRYPTION_KEY to long random values
make n8n-up                                # PostgreSQL ×2, Redis, n8n main + worker (queue mode)
N8N_OWNER_PASSWORD='<strong password>' make n8n-bootstrap   # creates the n8n owner + API key, writes N8N_API_KEY to .env
docker compose up -d --build api worker web
```

On start-up the API creates two n8n credentials (**AIVANTA Bridge**, **AIVANTA Model Gateway**). When you publish and run a canvas, the workflow appears in n8n as `AIVANTA · <tenant> · <graph hash>`, tagged `aivanta` and `tenant-<id>`, and each run is an n8n execution you can open from the run page.

Live tests against the running stack:

```bash
LIVE_N8N=1 LIVE_API=http://localhost:8000 N8N_API_KEY=<key> pytest -q tests/live
```

They publish and run Cloud Cost Review, Resource Deployment and RFP-to-SOW (with and without clarification gaps), decide every approval as the designated role, reject an approval, fail a node and retry the n8n execution from the failed node.

## Use real models

| Provider | Settings |
|---|---|
| OpenAI | `LLM_PROVIDER=openai`, `OPENAI_API_KEY` |
| Azure OpenAI | `LLM_PROVIDER=azure_openai`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, deployment names in `MODEL_ENTERPRISE_REASONING` / `MODEL_ENTERPRISE_FAST` |
| Local (Ollama, vLLM) | `MODEL_LOCAL_OPEN_WEIGHT=llama3.1:8b`, `OLLAMA_BASE_URL` |

n8n never holds model keys. The OpenAI Chat Model nodes call the AIVANTA gateway, which checks the tenant's allowlisted profile, calls the provider, meters tokens and cost per node, and returns an OpenAI-shaped response.

## What is where

```
apps/web                      Next.js portal: landing, Request Access, Provider Admin, Tenant Admin, canvas, runs, approvals, artifacts, pricing
apps/api                      FastAPI
  routers/bridge.py           n8n → AIVANTA: /internal/n8n/{op} and the OpenAI-compatible /gateway/v1
  routers/onboarding.py       access requests, tenant-admin approvals, provider console, plans, suspension
  models_relay.py             subscriptions (plan, status, cloud, n8n placement) and access requests
services/agent-runtime        aivanta_runtime
  n8n_compiler.py             canvas.v1 → n8n workflow JSON (joins, switches, waits, agents, retries)
  n8n_client.py               n8n REST client (+ in-process emulator)
  relay_adapter.py            RuntimeAdapter: deploy, trigger, resume, retry, outcome
  steps.py                    what each bridge call does (idempotent per run and node)
services/pricing, document-engine, connectors     shared AIVANTA services (deterministic pricing, DOCX/PDF/XLSX, tool gateway)
n8n/                          generated workflow files for every template, n8n operations notes
scripts/                      n8n_bootstrap.py, export_n8n_workflows.py
infra/docker, infra/terraform/{aws,azure,gcp}
tests/unit, tests/integration, tests/live, tests/e2e
docs/                         architecture, runtime, multi-tenancy, deployment, licensing, ADRs
```

## Roles

Tenant roles: Presales Engineer, Solution Architect, AI Engineer, Enterprise Architect, Finance / Commercial, PMO / Delivery, Governance Reviewer, Platform Administrator (= **Tenant Admin**). **Provider Admin** is a separate identity for the SaaS operator (`POST /api/provider/dev-login` in dev; OIDC role `aivanta-provider` in production).

## Before production

* **Licence.** n8n is fair-code (Sustainable Use License). Using Relay inside your own company is free. Offering it to external customers, where they use n8n through your product, requires a commercial **n8n Embed** licence. See [docs/licensing.md](docs/licensing.md).
* **Secrets.** Generate `AIVANTA_BRIDGE_TOKEN`, `N8N_ENCRYPTION_KEY` and `JWT_SECRET`; keep them in your cloud secrets service. Rotating the bridge token means updating the two n8n credentials (delete the credentials cache and restart the API).
* **Network.** Keep `/internal` and `/gateway` and the n8n editor private ([docs/deployment.md](docs/deployment.md)).
* **Prices, connectors, vectors, migrations, sessions.** As in the other editions: replace the illustrative price snapshot, point the connectors at real HRMS/Jira/SharePoint, add a pgvector column and index, generate the first Alembic migration, and serve web and API on one origin with an httpOnly session cookie.

See [COMPARISON.md](COMPARISON.md) for Relay next to the LangGraph (Conductor) and AutoGen (Ensemble) editions, and [docs/architecture/runtime.md](docs/architecture/runtime.md) for how the n8n runtime works.
