# ADR-0001: AIVANTA owns the canvas graph schema

**Status:** Accepted

**Context.** Visual agent builders (AutoGen Studio, LangGraph Studio) store graphs in their own formats and do not supply production tenancy, security, persistence or approvals.

**Decision.** AIVANTA persists its own versioned schema (`canvas.v1`, `packages/graph-schema`) and compiles it into the runtime through a backend adapter. The browser never sends executable code; only configuration that has passed validation reaches a runtime.

**Consequences.** The same canvas JSON runs on both editions (Conductor and Ensemble). Moving to another framework later, such as Microsoft Agent Framework, means writing a new adapter that passes `tests/integration/test_runtime_contract.py`.
