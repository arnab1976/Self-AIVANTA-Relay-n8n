# ADR-0003: Commercial numbers come only from the deterministic pricing engine

**Status:** Accepted

**Decision.** Person-months, labor, delivery cost and selling price are computed by `aivanta_pricing` using Decimal arithmetic, versioned rate cards and versioned FX rates. Agents may recommend levers (margin, discount, commercial model) and explain results, but never produce totals. Calculation nodes are deterministic and reproducible, and every price must pass a Human Approval before it can reach an End node.

**Consequences.** Totals reconcile exactly across runs, editions and exports. The engine reproduces the blueprint's worked example (30 PM × ₹1,80,000 + ₹16,00,000 at 30% margin = ₹1,00,00,000), and `tests/unit/test_pricing.py` checks it.
