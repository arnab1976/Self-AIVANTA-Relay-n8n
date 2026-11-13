# Relay vs Conductor vs Ensemble

AIVANTA is built on three runtimes on purpose. All three share the canvas schema (`canvas.v1`), API, database, portal, pricing engine, document engine, connectors, approvals and audit trail. Only the agent runtime differs, and the same contract tests (`tests/integration/test_runtime_contract.py`) pass in each repository.

| Concern | **Relay (n8n)** | Conductor (LangGraph) | Ensemble (AutoGen) |
|---|---|---|---|
| What runs the canvas | An **n8n workflow** compiled from the canvas, executed by n8n in queue mode | A LangGraph `StateGraph` in the AIVANTA worker | A run coordinator executing waves of AutoGen agents |
| Where you can see it | The n8n editor: every node, every execution and its data | Mermaid export; AIVANTA run timeline | AutoGen Studio export; AIVANTA run timeline |
| Agent call | n8n **AI Agent** node + OpenAI Chat Model on the AIVANTA gateway (or AIVANTA-executed) | LangChain structured output / `create_agent` | `AssistantAgent`; optional author-reviewer team |
| Human approval | n8n **Wait** node resumed by AIVANTA through `$execution.resumeUrl` | `interrupt()` + `Command(resume=…)` | Coordinator pauses; state in DB |
| Branching / joins | Switch per decision; Merge for parallel joins | Deactivated edges + waiting joins | Same as Conductor (shared executors) |
| Retries | n8n `retryOnFail` / `maxTries`; retry execution from failed node | Retry loop + checkpoint resume | Retry loop + persisted state |
| Scaling | n8n workers on Redis | AIVANTA workers + Postgres checkpointer | AIVANTA workers |
| Integrations | AIVANTA tool gateway (governed); n8n's 400+ nodes for platform-owned automations | Tool gateway | Tool gateway |
| Licence | n8n Sustainable Use (internal free; Embed licence for external SaaS) | MIT | MIT (maintenance mode) |
| Best fit | Teams that want visible, operable automation and many integrations | Precise, auditable control of agent flow | Conversational agent collaboration |

The canvas JSON moves between editions unchanged.
