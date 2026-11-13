# Runtime: n8n (AIVANTA Relay)

Code: `services/agent-runtime/aivanta_runtime/` — `n8n_compiler.py`, `n8n_client.py`, `relay_adapter.py`, `steps.py`, `llm_client.py`; API side `apps/api/aivanta_api/routers/bridge.py`.

## Division of labour

| n8n owns | AIVANTA owns |
|---|---|
| Trigger, execution order, branching (Switch / IF), joins (Merge) | What each step is allowed to do (tenant policy, RBAC, tool approvals) |
| Retries (`retryOnFail` / `maxTries`), pausing and resuming (Wait) | Prompts, model allowlists, token metering (model gateway) |
| Queue-mode scaling, execution history, retry from failed node | Tool calls (gateway with scopes, timeouts, idempotency ledger) |
| The visual workflow the platform team inspects | Deterministic pricing, artifacts, approvals with segregation of duties, audit |

Every governed step is an HTTP Request node that calls the **bridge** (`POST /internal/n8n/{op}`) with the run id, the canvas node id and `$execution.id`. AI Agent nodes call the **model gateway** (`/gateway/v1/chat/completions`). Both use the shared bridge token held in n8n credentials. n8n therefore never sees tenant secrets, model keys or other tenants' data.

## Compilation (`n8n_compiler.py`)

| Canvas node | n8n nodes |
|---|---|
| Start | **Webhook** `Trigger` (POST, header auth, respond immediately) → HTTP `Start · …` (records the execution id) |
| AI Agent (native) | HTTP `Prepare · …` → **AI Agent** (`@n8n/n8n-nodes-langchain.agent`) + **OpenAI Chat Model** sub-node (model `aivanta:<run>:<node>`, JSON mode) → HTTP `Record · …` |
| AI Agent (service) | one HTTP step; AIVANTA calls the model |
| Tool / Data / Calc / End | one HTTP step |
| Decision | HTTP `Evaluate · …` returns `{"route": label}` → **Switch** with one output per branch label |
| Human Approval | HTTP `Request approval · …` (sends `$execution.resumeUrl`) → **Wait** (resume on webhook) → HTTP `Decision · …` → **IF** approved |

**Joins.** Incoming edges are grouped by branch guards. Edges that can never fire together, such as "gaps found → clarification" and "no gaps" from the same decision, share one input. When a node has several parallel groups, a **Merge** node with one input per group waits for all of them. Data sources without inputs hang off the start step.

**Retries.** A node's `retry` budget becomes `retryOnFail` with `maxTries = retry + 1`. The bridge answers `503` for a transient error inside the budget and `422` when the budget is spent. Each step uses `executeOnce`, so a Merge never makes a step run twice.

**Versioning.** One n8n workflow exists per tenant and graph content hash (`AIVANTA · <tenant> · <hash>`). Publishing a new version creates a new workflow, so old executions keep pointing at the exact workflow they ran.

## Run lifecycle (`relay_adapter.py`)

1. **start**: compile → `POST /api/v1/workflows` (or reuse by name) → tag → activate → `POST /webhook/<path>` with `{run_id, tenant_id, project_id}` → wait.
2. **wait**: poll `GET /api/v1/executions/{id}` and the run state until the execution is `success` / `error` / `canceled`, or `waiting` with a pending approval.
3. **resume**: for each decided approval, `POST` the decision to the resume URL n8n handed over; n8n continues from the Wait node. Parallel approvals decided together are fed in turn.
4. **retry_failed**: `POST /api/v1/executions/{id}/retry` — n8n re-runs from the failed node. Bridge steps return stored results for completed nodes, so no work or external action is repeated.
5. **outcome**: node states, outputs, metrics, pending approvals and the n8n execution id come from the run state the bridge wrote. Nodes n8n never reached are marked `skipped`, immediately when a decision or rejection rules them out.

Any API replica can serve the bridge, and any worker can wait on a run, because all state is in the AIVANTA database.

## Model gateway

`POST /gateway/v1/chat/completions` accepts the OpenAI request n8n's Chat Model node sends. It:

1. parses `model = aivanta:<run>:<node>`;
2. checks that the node is an agent of that run and that its profile is on the tenant's allowlist (403 otherwise);
3. answers from the mock generator, or forwards to OpenAI / Azure OpenAI / Ollama;
4. records tokens and cost against the node, and returns an OpenAI-shaped response. It supports streaming.

`Record · …` then validates the agent's text against the template's typed schema. With a real model it runs one repair round through the same profile.

## Emulated mode

`N8N_MODE=emulated` interprets the compiled workflow in-process with n8n's v1 execution order (depth-first, output 0 first). It covers exactly the node types the compiler emits. The runtime contract tests run against it, and `tests/live` runs the same scenarios against a real n8n.

## Dedicated n8n per tenant

Enterprise-plan tenants can run on their own n8n:

```bash
N8N_TENANT_INSTANCES='{"<tenant_id>":{"api_url":"https://n8n-acme.internal/api/v1","webhook_url":"https://n8n-acme.internal","api_key_env":"N8N_API_KEY_ACME"}}'
```

The adapter keeps a client and credentials per instance. The bridge is unchanged.

## Version notes

* Tested with **n8n 2.45.7 on Node 24** (n8n 2.x requires Node ≥ 24). Node typeVersions emitted: Webhook 2, HTTP Request 4.2, Switch 3.2, IF 2.2, Wait 1.1, Merge 3, AI Agent 1.7, OpenAI Chat Model 1.2.
* `scripts/n8n_bootstrap.py` uses n8n's internal `/rest` endpoints for the owner and API key; if a future version changes them, create both in the UI.
