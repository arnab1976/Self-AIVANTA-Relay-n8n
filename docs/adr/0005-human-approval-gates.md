# ADR-0005: Human approval gates are graph nodes, enforced by validation

**Status:** Accepted

**Decision.** Approvals are first-class `approval` nodes with an approver role, an SLA and the evidence required. Validation rejects any external action (tool with `external: true`) or price (Calculation node) that is reachable without passing an approval. Approval decisions are recorded with segregation of duties and resume the run through the runtime contract.

**Consequences.** External emails, staffing commitments, pricing approvals and final SOW sign-off cannot happen without explicit human authorization, whichever runtime executes the graph.
