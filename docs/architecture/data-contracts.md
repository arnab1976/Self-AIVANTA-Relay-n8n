# Data contracts

## Entities (`apps/api/aivanta_api/models.py`)

| Entity | Essential fields |
|---|---|
| Tenant | code, currency, region, isolation_model, allowed_models, rate_card + version, fx_rate + version, margin floor, discount limit, price_snapshot_date |
| Project | code, client, industry, deal_stage, delivery_model, region, scope, deadline, currency, classification, clarifications, estimate_inputs, workload |
| Document / DocumentChunk | uploaded RFP (sha256, pages, PII redaction counts, scan engine, redacted text) and retrieval chunks with embeddings |
| CanvasGraphRow | draft graph (canvas.v1), template, saved_at |
| GraphVersion | immutable content, content_hash, environment (dev/staging/prod), published_by/at |
| AgentDefinition | template_id, version, instructions, model_profile, tools, policies |
| ExecutionRun | graph_version, graph_snapshot, mode, runtime, status, trace_id, idempotency_prefix, state, node_status, outputs, tokens, cost, error |
| RunEvent | type, node_id, data, dedupe_key |
| Approval | run_id, node_id, kind, approver_role, evidence, status, decided_by/at, comment |
| Artifact | type, version, content, source_ids, reviewer_role, approval_state, storage_uri |
| Estimate | version, inputs, result, scenarios, flags, selling_price, margin |
| ToolInvocation | idempotency ledger for external actions |
| AuditEvent | actor, role, action, entity, detail, prev_hash, hash (per-tenant chain) |

## Handoff envelope

Every handoff between nodes carries `project_id`, `run_id`, `graph_version`, the node output (typed by `output_schema`), source references, status and the schema version. Typed outputs are defined in `packages/agent-templates/aivanta_templates/schemas.py`:

`requirements.v1 → brd.v1 → sow.v1`, `architecture.v1`, `tech_matrix.v1`, `effort.v1`, `cloud_cost.v1`, `pricing.v1`, `staffing.v1`, `review.v1`.

## Illustrative node JSON

```json
{"id": "rfp_agent", "type": "agent", "name": "RFP Intelligence",
 "config": {"template": "RFP_INTELLIGENCE", "model_profile": "enterprise-reasoning",
            "input_schema": "rfp.v1", "output_schema": "requirements.v1",
            "tools": ["document_reader"], "timeout_s": 180, "retry": 2,
            "guardrails": ["cite_sources", "json_schema", "pii_redaction", "injection_filter"]}}
```

Credentials are referenced by vault IDs (`vault://…`) and never stored in canvas JSON. Validation rejects inline secrets.

## pgvector on PostgreSQL

Chunks store embeddings as JSON so SQLite works in development. On PostgreSQL:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE document_chunks ADD COLUMN embedding_vec vector(256);   -- 1536 for text-embedding-3-small
UPDATE document_chunks SET embedding_vec = (embedding::text)::vector;
CREATE INDEX ON document_chunks USING hnsw (embedding_vec vector_cosine_ops);
```

Then replace the in-Python cosine in `aivanta_connectors.retrieval.hybrid_search` with an `ORDER BY embedding_vec <=> :query` query filtered by `tenant_id` and `project_id`.
