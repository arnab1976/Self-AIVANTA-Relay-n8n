# ADR 0002 — n8n orchestrates; AIVANTA governs every step

**Status:** accepted · **Edition:** AIVANTA Relay

## Context

Relay must run AIVANTA canvases on n8n so that business and platform teams can see and operate workflows visually, while keeping the guarantees of the other editions: tenant isolation, model allowlists, tool approvals, deterministic pricing, human approval gates with segregation of duties, idempotent external actions and an audit trail. n8n Community Edition has no multi-tenancy, and anything placed in an n8n credential or Code node is visible to whoever edits the workflow.

## Decision

1. The AIVANTA canvas (`canvas.v1`) stays the source of truth (ADR 0001). Publishing compiles it into an n8n workflow; nobody edits AIVANTA workflows in the n8n editor.
2. n8n owns control flow: trigger, order, Switch/IF routing, Merge joins, retries, Wait-based pauses and queue-mode scaling.
3. Every governed step is an HTTP Request node calling the AIVANTA **bridge**, and every model call from an n8n AI Agent node goes through the AIVANTA **model gateway**. n8n holds only two service credentials (bridge token as Header Auth, and as an OpenAI key for the gateway).
4. Run state lives in the AIVANTA database, written by the bridge. Bridge operations are idempotent per (run, node).
5. One n8n workflow per (tenant, graph content hash), tagged with the tenant. Enterprise tenants may get a dedicated n8n instance.

## Consequences

* No tenant secrets, model keys or cross-tenant data in n8n. Changing a policy in AIVANTA takes effect on the next step without redeploying workflows.
* n8n's "retry from failed node" is safe, because completed steps replay their stored results.
* Workflows are readable in n8n, but they are compiled artefacts: change them on the canvas and publish again.
* Parallel branches run sequentially inside one n8n execution (n8n v1 order). Throughput comes from queue-mode workers running many executions.
* Serving external customers requires an n8n Embed licence (see docs/licensing.md).
