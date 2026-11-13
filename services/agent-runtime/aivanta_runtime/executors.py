"""Node behaviour shared by both runtimes.

Only *agent* execution differs between Conductor (LangChain) and Ensemble
(AutoGen). Tools, data retrieval, deterministic calculations, routing rules
and skip semantics are identical, so both editions produce the same results
for the same graph and project.
"""
from __future__ import annotations

import ast
import asyncio
import operator
import re
import time
from typing import Any, Awaitable, Callable

from aivanta_connectors import ToolError
from aivanta_graph import CanvasGraph, Node

from .contract import RunContext


class NodeExecutionError(Exception):
    def __init__(self, node_id: str, message: str, transient: bool = False):
        super().__init__(message)
        self.node_id = node_id
        self.transient = transient


class TransientSimulatedError(Exception):
    pass


# ---------------------------------------------------------------------------
# Skip semantics: a node runs when every predecessor has finished
# (succeeded or skipped) and at least one *active* incoming edge comes from a
# succeeded node. Decisions deactivate the branches they do not choose.
# ---------------------------------------------------------------------------
def is_live(graph: CanvasGraph, node_id: str, status: dict[str, str], edge_active: dict[str, bool]) -> bool:
    ins = graph.incoming(node_id)
    if not ins:
        return True
    return any(edge_active.get(e.id, True) and status.get(e.source) == "succeeded" for e in ins)


def ready(graph: CanvasGraph, node_id: str, status: dict[str, str]) -> bool:
    """All predecessors finished. A rejected approval counts as finished (its branch is then skipped)."""
    return all(status.get(e.source) in ("succeeded", "skipped", "failed") for e in graph.incoming(node_id))


def deactivate_outgoing(graph: CanvasGraph, node_id: str) -> dict[str, bool]:
    return {e.id: False for e in graph.outgoing(node_id)}


def ancestors(graph: CanvasGraph, node_id: str) -> set[str]:
    seen: set[str] = set()
    stack = [e.source for e in graph.incoming(node_id)]
    while stack:
        cur = stack.pop()
        if cur not in seen:
            seen.add(cur)
            stack.extend(e.source for e in graph.incoming(cur))
    return seen


def upstream_outputs(graph: CanvasGraph, node_id: str, outputs: dict[str, Any]) -> dict[str, Any]:
    anc = ancestors(graph, node_id)
    return {k: v for k, v in outputs.items() if k in anc}


def agent_context(ctx: RunContext, node: Node, upstream: dict[str, Any]) -> dict[str, Any]:
    rfp_text, availability = "", []
    for out in upstream.values():
        if isinstance(out, dict):
            data = out.get("data", out)
            if isinstance(data, dict) and data.get("text") and not rfp_text:
                rfp_text = data["text"]
            if isinstance(data, dict) and data.get("people"):
                availability = data["people"]
    return {"project": ctx.project, "upstream": {k: v for k, v in upstream.items() if not (isinstance(v, dict) and "text" in v.get("data", {}))},
            "rfp_text": rfp_text[:60000], "availability": availability}


# ---------------------------------------------------------------------------
# Safe rule evaluation for Decision nodes
# ---------------------------------------------------------------------------
_OPS = {ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Eq: operator.eq, ast.NotEq: operator.ne}


def eval_rule(rule: str, variables: dict[str, Any]) -> bool:
    tree = ast.parse(rule, mode="eval")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.BoolOp):
            vals = [ev(v) for v in n.values]
            return all(vals) if isinstance(n.op, ast.And) else any(vals)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            return not ev(n.operand)
        if isinstance(n, ast.Compare):
            left = ev(n.left)
            for op, comp in zip(n.ops, n.comparators):
                right = ev(comp)
                if type(op) not in _OPS or not _OPS[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(n, ast.Name):
            if n.id not in variables:
                raise ValueError(f"Unknown variable '{n.id}' in rule")
            return variables[n.id]
        if isinstance(n, ast.Constant):
            return n.value
        raise ValueError(f"Unsupported expression in rule: {ast.dump(n)}")

    return bool(ev(tree))


def decision_variables(ctx: RunContext, upstream: dict[str, Any]) -> dict[str, Any]:
    reqs, clar = [], []
    for out in upstream.values():
        if isinstance(out, dict) and "requirements" in out:
            reqs = out["requirements"]
            clar = out.get("clarifications", [])
    open_project = sum(1 for c in ctx.project.get("clarifications", []) if c.get("open"))
    return {"open_clarifications": max(open_project, len(clar)), "requirement_count": len(reqs),
            "low_confidence": sum(1 for r in reqs if r.get("confidence", 1) < 0.7)}


def choose_branch(ctx: RunContext, node: Node, upstream: dict[str, Any]) -> tuple[str, dict]:
    labels = [e.label or "" for e in ctx.graph.outgoing(node.id)]
    forced = node.config.get("sim_outcome", "auto")
    variables = decision_variables(ctx, upstream)
    if forced and forced != "auto" and forced in labels:
        return forced, variables
    result = eval_rule(node.config.get("rule", "False"), variables)
    positive = [lab for lab in labels if not re.search(r"\b(no|not|default|fallback|else)\b", lab, re.I)]
    negative = [lab for lab in labels if lab not in positive]
    if result:
        return (positive or labels)[0], variables
    return (negative or labels[-1:])[0], variables


def apply_branch(graph: CanvasGraph, node_id: str, label: str) -> dict[str, bool]:
    return {e.id: (e.label or "") == label for e in graph.outgoing(node_id)}


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------
async def with_retry(fn: Callable[[int], Awaitable[Any]], retries: int, on_retry: Callable[[int, Exception], Awaitable[None]]) -> Any:
    attempt = 0
    while True:
        try:
            return await fn(attempt)
        except (TransientSimulatedError, ToolError, NodeExecutionError, asyncio.TimeoutError) as exc:
            transient = isinstance(exc, (TransientSimulatedError, asyncio.TimeoutError)) or getattr(exc, "transient", False)
            if not transient or attempt >= retries:
                raise
            attempt += 1
            await on_retry(attempt, exc)
            await asyncio.sleep(min(2 ** attempt * 0.05, 2))


def maybe_fail(node: Node, attempt: int, already_failed: set[str]) -> None:
    """`fail_simulation` makes the first attempt fail with a transient error (demo of bounded retries)."""
    if node.config.get("fail_simulation") and attempt == 0 and node.id not in already_failed:
        already_failed.add(node.id)
        raise TransientSimulatedError(f"{node.name}: simulated transient error (HTTP 503)")


async def execute_tool(ctx: RunContext, node: Node, upstream: dict[str, Any], attempt: int) -> dict[str, Any]:
    c = node.config
    payload: dict[str, Any] = {"upstream_nodes": list(upstream.keys())}
    if c.get("tool_id") == "template_renderer":
        payload["artifacts"] = [k for k in upstream.keys()]
    if c.get("tool_id") == "sharepoint_search":
        payload["query"] = ctx.project.get("scope") or ctx.project.get("name", "")
    t0 = time.perf_counter()
    res = await ctx.gateway.invoke(c["tool_id"], c.get("operation", "call"), payload, ctx.tool_context(node.id), timeout_s=c.get("timeout_s"))
    res["latency_s"] = round(time.perf_counter() - t0, 3)
    return res


async def execute_data(ctx: RunContext, node: Node) -> dict[str, Any]:
    query = ctx.project.get("scope") or ctx.project.get("name", "")
    hits = ctx.retrieve(query, int(node.config.get("top_k", 6)))
    return {"knowledge_base": node.config.get("knowledge_base"), "filter": node.config.get("access_filter"),
            "passages": [{"text": h["text"][:500], "source": h.get("source"), "score": h.get("score")} for h in hits]}


def execute_calc(ctx: RunContext, node: Node, upstream: dict[str, Any]) -> dict[str, Any]:
    if node.config.get("formula") == "cloud_scenarios":
        workload = next((v["workload"] for v in upstream.values() if isinstance(v, dict) and "workload" in v), {})
        return {"cloud": ctx.cloud(workload)}
    return ctx.pricing(upstream, node.config)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
