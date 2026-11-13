"""Canvas validation rules (blueprint section 6).

The same rules run on save, on validate and as a hard gate on publish.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal

from pydantic import BaseModel

from .models import CanvasGraph, Node

Severity = Literal["error", "warning"]
SECRET_PATTERN = re.compile(r"(sk-[A-Za-z0-9]{8,}|password\s*[=:]|api[_-]?key\s*[=:]|BEGIN (RSA|EC|OPENSSH) PRIVATE KEY)", re.I)
MAX_PROMPT_CHARS = 4000


class Issue(BaseModel):
    severity: Severity
    code: str
    message: str
    node_id: str | None = None


class ValidationReport(BaseModel):
    issues: list[Issue]

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> dict:
        return {"ok": self.ok, "errors": len(self.errors), "warnings": len(self.warnings),
                "issues": [i.model_dump() for i in self.issues]}


@dataclass
class ToolPolicy:
    approved: bool
    external: bool


@dataclass
class ValidationPolicy:
    allowed_models: set[str] = field(default_factory=lambda: {"enterprise-reasoning", "enterprise-fast", "local-open-weight"})
    tools: dict[str, ToolPolicy] = field(default_factory=dict)
    known_templates: set[str] | None = None


def edge_problem(graph: CanvasGraph, source: str, target: str) -> str | None:
    """Live check used when a user drops a connection on the canvas."""
    a, b = graph.node(source), graph.node(target)
    if not a or not b:
        return "Both ends of a connection must be existing nodes."
    if source == target:
        return "A node cannot connect to itself."
    if b.type == "start":
        return "Start cannot have incoming connections."
    if a.type == "end":
        return "End cannot have outgoing connections."
    if b.type == "data":
        return "Data / RAG nodes are sources and take no inputs."
    if any(e.source == source and e.target == target for e in graph.edges):
        return "These nodes are already connected."
    if source in _reach(graph, [target]):
        return "This connection would create a cycle. Use a Decision with a bounded retry instead."
    return None


def _reach(graph: CanvasGraph, sources: Iterable[str], stop: callable = None) -> set[str]:
    """Nodes reachable from sources. `stop(node)` prevents expansion past that node."""
    seen: set[str] = set()
    stack = list(sources)
    srcs = set(stack)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        node = graph.node(cur)
        if stop and node and stop(node) and cur not in srcs:
            continue
        stack.extend(e.target for e in graph.outgoing(cur))
    return seen


def validate(graph: CanvasGraph, policy: ValidationPolicy | None = None) -> ValidationReport:
    policy = policy or ValidationPolicy()
    issues: list[Issue] = []

    def add(sev: Severity, code: str, msg: str, node: Node | None = None) -> None:
        issues.append(Issue(severity=sev, code=code, message=msg, node_id=node.id if node else None))

    ids = [n.id for n in graph.nodes]
    for dup in {i for i in ids if ids.count(i) > 1}:
        add("error", "duplicate_node", f"Node id '{dup}' is used more than once.")
    node_ids = set(ids)
    for e in graph.edges:
        if e.source not in node_ids or e.target not in node_ids:
            add("error", "dangling_edge", f"Connection {e.id} points to a node that does not exist.")
        else:
            prob = edge_problem(CanvasGraph(nodes=graph.nodes, edges=[x for x in graph.edges if x.id != e.id]), e.source, e.target)
            if prob:
                add("error", "invalid_edge", f"Invalid connection {e.id}: {prob}", graph.node(e.target))

    starts = [n for n in graph.nodes if n.type == "start"]
    ends = [n for n in graph.nodes if n.type == "end"]
    if len(starts) != 1:
        add("error", "start_count", f"Graph must have exactly one Start node (found {len(starts)}).")
    if not ends:
        add("error", "no_end", "Graph needs at least one End node.")

    sources = [n.id for n in starts] + [n.id for n in graph.nodes if n.type == "data"]
    reachable = _reach(graph, sources)
    for n in graph.nodes:
        if n.id not in reachable:
            add("error", "unreachable", f"'{n.name}' is not reachable from Start.", n)

    # reverse reachability to End
    to_end: set[str] = set()
    stack = [n.id for n in ends]
    while stack:
        cur = stack.pop()
        if cur in to_end:
            continue
        to_end.add(cur)
        stack.extend(e.source for e in graph.incoming(cur))
    for n in graph.nodes:
        if n.type != "end" and n.id not in to_end:
            add("error", "no_terminal_path", f"'{n.name}' has no path to an End node.", n)

    if len(graph.topological_order()) != len(graph.nodes):
        add("error", "cycle", "The graph contains a cycle. Use a Decision with bounded retry instead of loops.")

    no_approval_reach = _reach(graph, sources, stop=lambda n: n.type == "approval")

    for n in graph.nodes:
        c = n.config or {}
        if n.type == "agent":
            model = c.get("model_profile")
            if model not in policy.allowed_models:
                add("error", "model_not_allowed", f"'{n.name}' uses model profile '{model}', which is not allowed for this tenant.", n)
            if policy.known_templates is not None and c.get("template") not in policy.known_templates:
                add("error", "unknown_template", f"'{n.name}' references unknown agent template '{c.get('template')}'.", n)
            for tool_id in c.get("tools", []) or []:
                tp = policy.tools.get(tool_id)
                if tp is None:
                    add("error", "unknown_tool", f"'{n.name}' references unknown tool '{tool_id}'.", n)
                elif not tp.approved:
                    add("error", "tool_not_approved", f"'{n.name}' uses tool '{tool_id}', which is not approved.", n)
            if len(c.get("instructions", "") or "") > MAX_PROMPT_CHARS:
                add("warning", "prompt_too_long", f"'{n.name}' instructions exceed {MAX_PROMPT_CHARS} characters; keep prompts bounded.", n)
            if not c.get("input_schema") or not c.get("output_schema"):
                add("error", "schema_missing", f"'{n.name}' needs input and output schemas.", n)
            if "json_schema" not in (c.get("guardrails") or []):
                add("warning", "no_schema_guardrail", f"'{n.name}' output is not JSON-schema validated before downstream use.", n)
        elif n.type == "tool":
            tp = policy.tools.get(c.get("tool_id", ""))
            if tp is None:
                add("error", "unknown_tool", f"'{n.name}' has no registered connector selected.", n)
            else:
                if not tp.approved:
                    add("error", "tool_not_approved", f"'{n.name}' uses '{c.get('tool_id')}', which is not an approved endpoint.", n)
                if tp.external and n.id in no_approval_reach:
                    add("error", "external_without_approval",
                        f"'{n.name}' performs an external action on a path with no Human Approval before it.", n)
            if not str(c.get("credential_ref", "")).startswith("vault://"):
                add("error", "inline_credential", f"'{n.name}' credential must be a vault:// reference.", n)
        elif n.type == "decision":
            outs = graph.outgoing(n.id)
            if len(outs) < 2:
                add("error", "decision_branches", f"'{n.name}' needs at least two outgoing branches.", n)
            if any(not (e.label or "").strip() for e in outs):
                add("warning", "unlabeled_branch", f"Label every branch leaving '{n.name}' so routing is deterministic.", n)
        elif n.type == "approval":
            if not c.get("approver_role"):
                add("error", "approver_missing", f"'{n.name}' needs an approver role.", n)
        elif n.type == "calc":
            if not c.get("rate_card_version"):
                add("error", "rate_card_missing", f"'{n.name}' must reference a versioned rate card.", n)
            past = _reach(graph, [n.id], stop=lambda x: x.type == "approval")
            if any(e.id in past for e in ends):
                add("error", "price_without_approval", f"Price from '{n.name}' can reach End without a Human Approval.", n)
        elif n.type == "data":
            if "project" not in str(c.get("access_filter", "")):
                add("warning", "unscoped_retrieval", f"'{n.name}' retrieval is not filtered to the project.", n)
        blob = repr(c)
        if SECRET_PATTERN.search(blob):
            add("error", "inline_secret", f"'{n.name}' contains what looks like an inline secret. Use a vault reference.", n)

    return ValidationReport(issues=issues)
