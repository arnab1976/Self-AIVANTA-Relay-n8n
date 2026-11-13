"""Compile an AIVANTA canvas graph (canvas.v1) into an n8n workflow.

n8n is the orchestrator: it owns the trigger, ordering, branching, joins,
retries and the pause/resume of human approvals. Every governed step calls
back into AIVANTA through the **bridge** (`/internal/n8n/{op}`), so tenant
policy, model allowlists, the tool gateway, deterministic pricing, the audit
trail and artifact versioning stay in one place, whichever n8n instance runs
the workflow.

Node mapping
------------
=============  =========================================================================================
canvas node    n8n nodes
=============  =========================================================================================
start          Webhook ``Trigger`` (header-auth) → HTTP ``Start · <name>`` (records the execution id)
agent          native mode: HTTP ``Prepare`` → **AI Agent** (+ OpenAI Chat Model → AIVANTA model gateway)
               → HTTP ``Record`` (schema validation); service mode: one HTTP step
tool / data    HTTP step (tool gateway / tenant-filtered retrieval)
calc           HTTP step (deterministic pricing engine, no LLM)
decision       HTTP step (rule evaluation) → **Switch** with one output per branch label
approval       HTTP ``Request approval`` (passes ``$execution.resumeUrl``) → **Wait** (resume on webhook)
               → HTTP ``Decision`` → **IF** approved
end            HTTP step (marks the run's end)
=============  =========================================================================================

Joins
-----
Incoming canvas edges are grouped into *alternatives*: edges whose branch
guards contradict each other (e.g. "gaps found" vs "no gaps" of the same
decision) can never both fire, so they share one input. When a node has more
than one group, a **Merge** node with one input per group waits for every
parallel branch. Data sources without inputs hang off the start step.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from aivanta_graph import CanvasGraph, Node

TRIGGER = "Trigger"
BRIDGE_CREDENTIAL = "AIVANTA Bridge"
GATEWAY_CREDENTIAL = "AIVANTA Model Gateway"

# n8n node type identifiers and the typeVersions this compiler targets (n8n 1.80+ / 2.x)
T_WEBHOOK = ("n8n-nodes-base.webhook", 2)
T_HTTP = ("n8n-nodes-base.httpRequest", 4.2)
T_SWITCH = ("n8n-nodes-base.switch", 3.2)
T_IF = ("n8n-nodes-base.if", 2.2)
T_WAIT = ("n8n-nodes-base.wait", 1.1)
T_MERGE = ("n8n-nodes-base.merge", 3)
T_AGENT = ("@n8n/n8n-nodes-langchain.agent", 1.7)
T_CHAT = ("@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.2)


class CompileError(ValueError):
    pass


@dataclass
class CompileOptions:
    bridge_url: str = "http://api:8000"
    agent_mode: str = "native"            # native (n8n AI Agent node) | service (AIVANTA executes the agent)
    bridge_credential_id: str = "aivanta-bridge"
    gateway_credential_id: str = "aivanta-gateway"
    webhook_path: str = "aivanta/run"
    workflow_name: str = "AIVANTA workflow"
    tags: list[str] = field(default_factory=list)


@dataclass
class _Compiled:
    entry: str                                   # n8n node that receives this canvas node's input
    exits: dict[str, tuple[str, int]]            # branch label ("" = default) -> (n8n node, output index)


def _uid(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"aivanta:{seed}"))


class _Builder:
    def __init__(self, graph: CanvasGraph, opt: CompileOptions):
        self.g, self.opt = graph, opt
        self.nodes: list[dict[str, Any]] = []
        self.conn: dict[str, dict[str, list[list[dict]]]] = {}
        self.names: set[str] = set()

    # ---- primitives ------------------------------------------------------
    def name(self, base: str) -> str:
        base = base.replace("'", "’")
        n, i = base, 2
        while n in self.names:
            n, i = f"{base} ({i})", i + 1
        self.names.add(n)
        return n

    def add(self, base: str, typ: tuple[str, float], params: dict, pos: tuple[float, float], **extra) -> str:
        name = self.name(base)
        node = {"id": _uid(f"{self.opt.workflow_name}:{name}"), "name": name, "type": typ[0], "typeVersion": typ[1],
                "position": [round(pos[0]), round(pos[1])], "parameters": params}
        node.update({k: v for k, v in extra.items() if v is not None})
        self.nodes.append(node)
        return name

    def link(self, src: str, dst: str, out: int = 0, inp: int = 0, kind: str = "main") -> None:
        outs = self.conn.setdefault(src, {}).setdefault(kind, [])
        while len(outs) <= out:
            outs.append([])
        target = {"node": dst, "type": kind, "index": inp}
        if target not in outs[out]:
            outs[out].append(target)

    def bridge(self, base: str, op: str, node_id: str, pos, extra_fields: dict[str, str] | None = None, retries: int = 0,
               timeout_s: int = 300, note: str = "") -> str:
        fields = {"run_id": f"$('{TRIGGER}').first().json.body.run_id", "node_id": json.dumps(node_id), "execution_id": "$execution.id"}
        fields.update(extra_fields or {})
        body = "={{ JSON.stringify({ " + ", ".join(f"{k}: {v}" for k, v in fields.items()) + " }) }}"
        params = {"method": "POST", "url": f"{self.opt.bridge_url.rstrip('/')}/internal/n8n/{op}",
                  "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                  "sendBody": True, "specifyBody": "json", "jsonBody": body, "options": {"timeout": timeout_s * 1000}}
        tries = max(0, int(retries or 0)) + 1
        return self.add(base, T_HTTP, params, pos, credentials={"httpHeaderAuth": {"id": self.opt.bridge_credential_id, "name": BRIDGE_CREDENTIAL}},
                        executeOnce=True, retryOnFail=tries > 1 or None, maxTries=min(5, max(2, tries)) if tries > 1 else None,
                        waitBetweenTries=1000 if tries > 1 else None, notes=f"{note or 'AIVANTA bridge'} · {op} · node {node_id}")

    # ---- canvas nodes ----------------------------------------------------
    def compile_node(self, n: Node) -> _Compiled:
        x, y = n.position.x * 1.25, n.position.y + 300
        c = n.config or {}
        retries = int(c.get("retry", 0) or 0)
        timeout = int(c.get("timeout_s", 300) or 300)
        if n.type == "start":
            trig = self.add(TRIGGER, T_WEBHOOK, {"httpMethod": "POST", "path": self.opt.webhook_path, "authentication": "headerAuth",
                                                  "responseMode": "onReceived", "options": {}}, (x - 220, y),
                            webhookId=_uid(f"{self.opt.webhook_path}:trigger"),
                            credentials={"httpHeaderAuth": {"id": self.opt.bridge_credential_id, "name": BRIDGE_CREDENTIAL}},
                            notes="Started by the AIVANTA API (POST with run_id). Header auth = AIVANTA Bridge credential.")
            step = self.bridge(f"Start · {n.name}", "start", n.id, (x, y))
            self.link(trig, step)
            return _Compiled(step, {"": (step, 0)})
        if n.type == "agent" and self.opt.agent_mode == "native":
            prep = self.bridge(f"Prepare · {n.name}", "agent_prepare", n.id, (x - 160, y), retries=retries,
                               note="Builds the governed prompt: template, tenant overrides, redacted RFP, upstream artifacts, output schema.")
            agent = self.add(n.name, T_AGENT, {"promptType": "define", "text": "={{ $json.task }}", "hasOutputParser": False,
                                              "options": {"systemMessage": "={{ $json.system }}", "maxIterations": 6}}, (x, y),
                             retryOnFail=True if retries else None, maxTries=min(5, retries + 1) if retries else None,
                             notes=f"AIVANTA agent template {c.get('template')} · profile {c.get('model_profile', 'enterprise-fast')}")
            model = self.add(f"Model · {n.name}", T_CHAT, {"model": {"__rl": True, "mode": "id", "value": f"={{{{ $('{prep}').first().json.model }}}}"},
                                                          "options": {"responseFormat": "json_object", "temperature": 0.1, "timeout": timeout * 1000, "maxRetries": 1}},
                             (x, y + 200), credentials={"openAiApi": {"id": self.opt.gateway_credential_id, "name": GATEWAY_CREDENTIAL}},
                             notes="OpenAI-compatible AIVANTA model gateway: enforces the tenant model allowlist and records tokens and cost.")
            rec = self.bridge(f"Record · {n.name}", "agent_record", n.id, (x + 180, y), extra_fields={"text": "$json.output"},
                              note="Validates the agent output against its typed schema and stores it as a run output.")
            self.link(prep, agent)
            self.link(model, agent, kind="ai_languageModel")
            self.link(agent, rec)
            return _Compiled(prep, {"": (rec, 0)})
        if n.type == "decision":
            step = self.bridge(f"Evaluate · {n.name}", "step", n.id, (x - 120, y), retries=retries)
            labels = [e.label or "" for e in self.g.outgoing(n.id)]
            uniq = list(dict.fromkeys(labels))
            rules = [{"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                                     "conditions": [{"id": _uid(f"{n.id}:{lab}"), "leftValue": "={{ $json.route }}", "rightValue": lab,
                                                     "operator": {"type": "string", "operation": "equals"}}], "combinator": "and"},
                      "renameOutput": True, "outputKey": lab or "default"} for lab in uniq]
            sw = self.add(n.name, T_SWITCH, {"rules": {"values": rules}, "options": {}}, (x + 60, y), notes=f"Rule: {c.get('rule', '')}")
            self.link(step, sw)
            return _Compiled(step, {lab: (sw, i) for i, lab in enumerate(uniq)})
        if n.type == "approval":
            req = self.bridge(f"Request approval · {n.name}", "approval_request", n.id, (x - 200, y), extra_fields={"resume_url": "$execution.resumeUrl"},
                              note=f"Creates the approval for role {c.get('approver_role')} and hands AIVANTA the resume URL.")
            wait = self.add(f"Wait · {n.name}", T_WAIT, {"resume": "webhook", "httpMethod": "POST", "options": {}}, (x - 40, y),
                            webhookId=_uid(f"{self.opt.webhook_path}:{n.id}:wait"),
                            notes="Execution pauses here until the approver decides in AIVANTA (segregation of duties enforced there).")
            dec = self.bridge(f"Decision · {n.name}", "approval_result", n.id, (x + 120, y), extra_fields={"decision": "$json.body"})
            ok = self.add(n.name, T_IF, {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                                                       "conditions": [{"id": _uid(f"{n.id}:approved"), "leftValue": "={{ $json.approved }}", "rightValue": True,
                                                                       "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                                                       "combinator": "and"}, "options": {}}, (x + 280, y), notes="Rejected → the branch stops and the run fails.")
            self.link(req, wait)
            self.link(wait, dec)
            self.link(dec, ok)
            return _Compiled(req, {"": (ok, 0)})
        step = self.bridge(n.name, "step", n.id, (x, y), retries=retries, timeout_s=timeout,
                           note={"tool": f"Tool gateway · {c.get('tool_id')} · {c.get('operation')}",
                                 "data": f"Tenant-filtered retrieval · {c.get('knowledge_base')}",
                                 "calc": "Deterministic pricing engine on the tenant rate card (no LLM)",
                                 "agent": f"AIVANTA executes agent template {c.get('template')}",
                                 "end": "Marks the end of the AIVANTA run"}.get(n.type, ""))
        return _Compiled(step, {"": (step, 0)})


def _guards(graph: CanvasGraph) -> dict[str, frozenset]:
    """For every edge: the (decision, label) choices that must hold for it to carry data."""
    node_guard: dict[str, frozenset] = {}
    edge_guard: dict[str, frozenset] = {}
    for nid in graph.topological_order():
        ins = graph.incoming(nid)
        gs = [edge_guard.get(e.id, frozenset()) for e in ins]
        node_guard[nid] = frozenset.intersection(*gs) if gs else frozenset()
        node = graph.node(nid)
        for e in graph.outgoing(nid):
            g = node_guard[nid]
            if node and node.type == "decision":
                g = g | {(nid, e.label or "")}
            edge_guard[e.id] = g
    return edge_guard


def _conflict(a: frozenset, b: frozenset) -> bool:
    da = dict(a)
    return any(d in da and da[d] != lab for d, lab in b)


def compile_workflow(graph: CanvasGraph, opt: CompileOptions | None = None) -> dict[str, Any]:
    opt = opt or CompileOptions()
    if len(graph.topological_order()) != len(graph.nodes):
        raise CompileError("The canvas contains a cycle; n8n workflows compiled by AIVANTA must be acyclic.")
    starts = [n for n in graph.nodes if n.type == "start"]
    if len(starts) != 1:
        raise CompileError("Exactly one Start node is required.")
    b = _Builder(graph, opt)
    compiled: dict[str, _Compiled] = {}
    for nid in graph.topological_order():
        compiled[nid] = b.compile_node(graph.node(nid))
    start_exit = compiled[starts[0].id].exits[""]
    guards = _guards(graph)

    for n in graph.nodes:
        target = compiled[n.id].entry
        ins = graph.incoming(n.id)
        if not ins:
            if n.type != "start":   # data sources and stray roots hang off the start step
                b.link(start_exit[0], target, start_exit[1])
            continue
        groups: list[list] = []
        for e in ins:
            g = guards[e.id]
            for grp in groups:
                if all(_conflict(g, guards[o.id]) for o in grp):
                    grp.append(e)
                    break
            else:
                groups.append([e])

        def exit_of(e):
            src = compiled[e.source]
            return src.exits.get(e.label or "", src.exits.get("", next(iter(src.exits.values()))))

        if len(groups) == 1:
            for e in groups[0]:
                node_name, out = exit_of(e)
                b.link(node_name, target, out)
            continue
        pos = next(x["position"] for x in b.nodes if x["name"] == target)
        merge = b.add(f"Join · {n.name}", T_MERGE, {"numberInputs": len(groups)}, (pos[0] - 150, pos[1] + 120),
                      notes="Waits for every parallel branch before continuing.")
        for i, grp in enumerate(groups):
            for e in grp:
                node_name, out = exit_of(e)
                b.link(node_name, merge, out, i)
        b.link(merge, target)

    return {"name": opt.workflow_name, "nodes": b.nodes, "connections": b.conn,
            "settings": {"executionOrder": "v1", "saveDataSuccessExecution": "all", "saveDataErrorExecution": "all",
                         "saveExecutionProgress": True, "saveManualExecutions": True, "timezone": "UTC"},
            "meta": {"aivanta": {"graph_hash": graph.content_hash(), "webhook_path": opt.webhook_path, "agent_mode": opt.agent_mode,
                                 "tags": opt.tags}}}


def node_map(workflow: dict[str, Any]) -> dict[str, list[str]]:
    """canvas node id -> the n8n node names compiled for it (for the run timeline and debugging)."""
    out: dict[str, list[str]] = {}
    for n in workflow["nodes"]:
        note = n.get("notes", "")
        if "· node " in note:
            out.setdefault(note.rsplit("· node ", 1)[1].strip(), []).append(n["name"])
    return out
