"""The AIVANTA side of the n8n bridge.

n8n calls these operations for every governed step of a compiled workflow:

=================  ===========================================================================
op                 what AIVANTA does
=================  ===========================================================================
start              record the n8n execution id; mark the Start node succeeded
step               execute a tool / data / calc / decision / end node (or a whole agent in
                   service mode); decisions return ``{"route": <branch label>}``
agent_prepare      build the governed prompt for an n8n AI Agent node
chat               (model gateway) answer an AI Agent node's model call for the tenant profile
agent_record       validate the AI Agent's output against its typed schema and store it
approval_request   create the human approval and keep n8n's resume URL
approval_result    record the decision that resumed n8n's Wait node
=================  ===========================================================================

Every operation is idempotent per (run, node): n8n retries and "retry from
failed node" never repeat completed work or external side effects. All state
lives in the run record (``ctx.load_state`` / ``ctx.save_state``), so any API
replica can serve any call.
"""
from __future__ import annotations

import json
import time
from typing import Any

from aivanta_graph import Node
from aivanta_templates import get_template, mock_output, output_model
from pydantic import ValidationError

from . import llm_client
from .contract import Decision, RunContext
from .executors import (NodeExecutionError, TransientSimulatedError, agent_context, apply_branch, choose_branch, deactivate_outgoing, estimate_tokens,
                        execute_calc, execute_data, execute_tool, is_live, ready, upstream_outputs)
from .llm_settings import LLMSettings
from .prompts import build_task, extract_json


class BridgeError(Exception):
    """Mapped to HTTP by the bridge router: transient → 503 (n8n retries), conflict → 409, otherwise 422."""

    def __init__(self, message: str, transient: bool = False, conflict: bool = False):
        super().__init__(message)
        self.transient, self.conflict = transient, conflict

    @property
    def status_code(self) -> int:
        return 409 if self.conflict else 503 if self.transient else 422


def empty_state() -> dict[str, Any]:
    return {"status": {}, "outputs": {}, "metrics": {}, "pending": {}, "attempts": {}, "failed_once": [], "started": [],
            "decisions": {}, "log": [], "n8n": {}, "halted": None, "error": None, "edge_active": {}}


class StepExecutor:
    def __init__(self, ctx: RunContext, agent_mode: str = "native"):
        self.ctx, self.agent_mode = ctx, agent_mode

    # ---- state helpers ---------------------------------------------------
    def state(self) -> dict[str, Any]:
        st = self.ctx.load_state() or {}
        base = empty_state()
        base.update(st)
        return base

    def save(self, st: dict[str, Any]) -> None:
        self.ctx.save_state(st)

    def node(self, node_id: str) -> Node:
        n = self.ctx.graph.node(node_id)
        if n is None:
            raise BridgeError(f"Unknown node '{node_id}' for run {self.ctx.run_id}")
        return n

    def _guard(self, st: dict[str, Any], node: Node) -> None:
        if self.ctx.is_cancelled():
            raise BridgeError("Run cancelled in AIVANTA", conflict=True)
        if st.get("halted"):
            raise BridgeError(f"Run halted: {st['halted']}", conflict=True)

    async def _started(self, st: dict, node: Node) -> None:
        if node.id not in st["started"]:
            st["started"].append(node.id)
            st["status"][node.id] = "running"
            self.save(st)
            await self.ctx.emit("node_started", node.id, {"type": node.type, "name": node.name})

    def _attempt(self, st: dict, node: Node) -> int:
        n = int(st["attempts"].get(node.id, 0))
        st["attempts"][node.id] = n + 1
        return n

    async def _transient_or_fail(self, st: dict, node: Node, exc: Exception) -> BridgeError:
        """Within the node's retry budget: emit node_retry and answer 503 so n8n retries.
        Budget exhausted (or a hard error): mark the node failed and answer 422 so the execution stops."""
        transient = isinstance(exc, (TransientSimulatedError, llm_client.ProviderError, TimeoutError)) or getattr(exc, "transient", False)
        budget = int(node.config.get("retry", 0) or 0)
        used = int(st["attempts"].get(node.id, 1))
        if transient and used <= budget:
            self.save(st)
            await self.ctx.emit("node_retry", node.id, {"attempt": used, "error": str(exc)})
            return BridgeError(str(exc), transient=True)
        st["status"][node.id] = "failed"
        st["error"] = f"{node.id}: {exc}"
        self.save(st)
        await self.ctx.emit("node_failed", node.id, {"error": str(exc)})
        return BridgeError(str(exc))

    async def _succeed(self, st: dict, node: Node, out: Any, metrics: dict) -> None:
        st["status"][node.id] = "succeeded"
        st["outputs"][node.id] = out
        st["metrics"][node.id] = metrics
        if st.get("error", "") and str(st["error"]).startswith(f"{node.id}:"):
            st["error"] = None
        self.save(st)
        await self.ctx.emit("node_succeeded", node.id, metrics)

    def _cached(self, st: dict, node: Node) -> dict | None:
        if st["status"].get(node.id) != "succeeded":
            return None
        out = st["outputs"].get(node.id)
        res = {"ok": True, "cached": True, "node_id": node.id}
        if node.type == "decision" and isinstance(out, dict):
            res["route"] = out.get("selected")
        return res

    # ---- dispatch --------------------------------------------------------
    async def handle(self, op: str, body: dict[str, Any]) -> dict[str, Any]:
        fn = {"start": self.op_start, "step": self.op_step, "agent_prepare": self.op_agent_prepare, "agent_record": self.op_agent_record,
              "approval_request": self.op_approval_request, "approval_result": self.op_approval_result}.get(op)
        if fn is None:
            raise BridgeError(f"Unknown bridge operation '{op}'")
        return await fn(body)

    async def op_start(self, body: dict) -> dict:
        st = self.state()
        node = self.node(body["node_id"])
        if body.get("execution_id"):
            st["n8n"]["execution_id"] = str(body["execution_id"])
            st["n8n"].setdefault("executions", [])
            if str(body["execution_id"]) not in st["n8n"]["executions"]:
                st["n8n"]["executions"].append(str(body["execution_id"]))
        if (c := self._cached(st, node)) is not None:
            self.save(st)
            return c
        await self._started(st, node)
        await self._succeed(st, node, {"schema": node.config.get("input_schema", "project.v1")}, {"tokens": 0, "cost": 0})
        return {"ok": True, "node_id": node.id}

    async def op_step(self, body: dict) -> dict:
        st = self.state()
        node = self.node(body["node_id"])
        if (c := self._cached(st, node)) is not None:
            return c
        self._guard(st, node)
        await self._started(st, node)
        attempt = self._attempt(st, node)
        upstream = upstream_outputs(self.ctx.graph, node.id, st["outputs"])
        try:
            self._maybe_fail(st, node, attempt)
            if node.type == "agent":
                out, metrics = await self.run_agent_service(node, upstream)
            elif node.type == "tool":
                out = await execute_tool(self.ctx, node, upstream, attempt)
                metrics = {"latency_s": out.get("latency_s", 0), "tokens": 0, "cost": 0}
            elif node.type == "data":
                out, metrics = await execute_data(self.ctx, node), {"tokens": 0, "cost": 0}
            elif node.type == "calc":
                out, metrics = execute_calc(self.ctx, node, upstream), {"tokens": 0, "cost": 0, "deterministic": True}
            elif node.type == "decision":
                label, variables = choose_branch(self.ctx, node, upstream)
                out, metrics = {"selected": label, "variables": variables}, {"tokens": 0, "cost": 0}
            else:  # end
                out, metrics = {"schema": node.config.get("output_schema", "proposal_package.v1")}, {"tokens": 0, "cost": 0}
        except BridgeError:
            raise
        except Exception as exc:
            raise await self._transient_or_fail(st, node, exc) from exc
        await self._succeed(st, node, out, metrics)
        res: dict[str, Any] = {"ok": True, "node_id": node.id}
        if node.type == "decision":
            res["route"] = out["selected"]
            await self.ctx.emit("route_selected", node.id, {"label": out["selected"], "variables": out["variables"]})
            st = self.state()
            st["edge_active"].update(apply_branch(self.ctx.graph, node.id, out["selected"]))
            await self.propagate_skips(st)
        return res

    async def propagate_skips(self, st: dict) -> None:
        """Mark nodes on branches n8n will never execute as skipped right away (same semantics as the other runtimes):
        a node is skipped when all its predecessors are finished and no active incoming edge comes from a succeeded node."""
        g, changed = self.ctx.graph, True
        while changed:
            changed = False
            for nid in g.topological_order():
                if st["status"].get(nid) not in (None, "pending") or not g.incoming(nid):
                    continue
                if ready(g, nid, st["status"]) and not is_live(g, nid, st["status"], st["edge_active"]):
                    st["status"][nid] = "skipped"
                    st["edge_active"].update(deactivate_outgoing(g, nid))
                    await self.ctx.emit("node_skipped", nid, {})
                    changed = True
        self.save(st)

    def _maybe_fail(self, st: dict, node: Node, attempt: int) -> None:
        if node.config.get("fail_simulation") and node.id not in st["failed_once"]:
            st["failed_once"].append(node.id)
            self.save(st)
            raise TransientSimulatedError(f"{node.name}: simulated transient error (HTTP 503)")

    # ---- agents ----------------------------------------------------------
    def prompts(self, node: Node, upstream: dict) -> dict[str, Any]:
        cfg = node.config
        tpl = get_template(cfg["template"])
        schema_id = cfg.get("output_schema") or tpl.output_schema
        model_cls = output_model(schema_id)
        actx = agent_context(self.ctx, node, upstream)
        override = (self.ctx.agent_overrides.get(tpl.id) or {}).get("instructions") or cfg.get("instructions")
        return {"tpl": tpl, "schema_id": schema_id, "model_cls": model_cls, "profile": cfg.get("model_profile") or tpl.default_model,
                "actx": actx, "system": tpl.system_prompt(override), "task": build_task(actx, schema_id, model_cls)}

    def _metrics(self, profile: str, tokens: int, t0: float, model: str) -> dict:
        return {"tokens": tokens, "latency_s": round(time.perf_counter() - t0, 3), "model": model,
                "cost": LLMSettings.cost(profile, tokens, self.ctx.fx_rate), "framework": "n8n"}

    async def run_agent_service(self, node: Node, upstream: dict) -> tuple[dict, dict]:
        """Service mode: AIVANTA executes the agent inside the bridge step."""
        p = self.prompts(node, upstream)
        t0 = time.perf_counter()
        if self.ctx.llm.provider_for(p["profile"]) == "mock":
            out = mock_output(p["tpl"].id, p["actx"])
            tokens = estimate_tokens(p["system"] + p["task"]) + estimate_tokens(json.dumps(out))
            return out, self._metrics(p["profile"], tokens, t0, f"mock:{p['profile']}")
        text, usage, model = await llm_client.chat(self.ctx.llm, p["profile"], [{"role": "system", "content": p["system"]}, {"role": "user", "content": p["task"]}])
        out = self._validate(node, p["model_cls"], text)
        return out, self._metrics(p["profile"], usage["total_tokens"] or estimate_tokens(p["system"] + p["task"] + text), t0, model)

    def _validate(self, node: Node, model_cls, text: str) -> dict:
        try:
            raw = extract_json(text) if isinstance(text, str) else text
            return model_cls.model_validate(raw).model_dump()
        except (ValueError, ValidationError) as exc:
            raise NodeExecutionError(node.id, f"Output failed schema validation: {str(exc)[:400]}", transient=True) from exc

    async def op_agent_prepare(self, body: dict) -> dict:
        st = self.state()
        node = self.node(body["node_id"])
        if node.type != "agent":
            raise BridgeError(f"{node.id} is not an agent node")
        self._guard(st, node)
        if st["status"].get(node.id) == "succeeded":   # n8n retry after success: replay the stored output instead of re-asking the model
            p = self.prompts(node, upstream_outputs(self.ctx.graph, node.id, st["outputs"]))
            return {"system": p["system"], "task": p["task"], "model": f"aivanta:{self.ctx.run_id}:{node.id}", "cached": True}
        await self._started(st, node)
        attempt = self._attempt(st, node)
        try:
            self._maybe_fail(st, node, attempt)
        except Exception as exc:
            raise await self._transient_or_fail(st, node, exc) from exc
        p = self.prompts(node, upstream_outputs(self.ctx.graph, node.id, st["outputs"]))
        st.setdefault("prepared", {})[node.id] = {"profile": p["profile"], "t0": time.time()}
        self.save(st)
        return {"system": p["system"], "task": p["task"], "model": f"aivanta:{self.ctx.run_id}:{node.id}", "profile": p["profile"],
                "output_schema": p["schema_id"]}

    async def chat(self, node_id: str, messages: list[dict[str, Any]]) -> tuple[str, dict[str, int], str]:
        """Model gateway call from an n8n AI Agent node. Returns (content, usage, model)."""
        st = self.state()
        node = self.node(node_id)
        self._guard(st, node)
        if st["status"].get(node.id) == "succeeded":
            return json.dumps(st["outputs"][node.id]), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, "replay"
        p = self.prompts(node, upstream_outputs(self.ctx.graph, node.id, st["outputs"]))
        if self.ctx.llm.provider_for(p["profile"]) == "mock":
            content = json.dumps(mock_output(p["tpl"].id, p["actx"]))
            prompt_tokens = estimate_tokens(json.dumps(messages))
            usage = {"prompt_tokens": prompt_tokens, "completion_tokens": estimate_tokens(content), "total_tokens": prompt_tokens + estimate_tokens(content)}
            model = f"mock:{p['profile']}"
        else:
            content, usage, model = await llm_client.chat(self.ctx.llm, p["profile"], messages)
        acc = st.setdefault("usage", {}).setdefault(node.id, {"tokens": 0, "calls": 0, "model": model})
        acc["tokens"] += int(usage.get("total_tokens", 0))
        acc["calls"] += 1
        acc["model"] = model
        self.save(st)
        await self.ctx.emit("agent_message", node.id, {"source": "n8n AI Agent", "model": model, "tokens": usage.get("total_tokens", 0)})
        return content, usage, model

    async def op_agent_record(self, body: dict) -> dict:
        st = self.state()
        node = self.node(body["node_id"])
        if (c := self._cached(st, node)) is not None:
            return c
        self._guard(st, node)
        p = self.prompts(node, upstream_outputs(self.ctx.graph, node.id, st["outputs"]))
        text = body.get("text")
        try:
            out = self._validate(node, p["model_cls"], text if isinstance(text, str) else json.dumps(text))
        except NodeExecutionError as first:
            if self.ctx.llm.provider_for(p["profile"]) == "mock":
                raise await self._transient_or_fail(st, node, NodeExecutionError(node.id, str(first))) from first
            try:  # one repair round through the same gateway profile
                fixed, _, _ = await llm_client.chat(self.ctx.llm, p["profile"], [
                    {"role": "system", "content": "Return only a JSON object that matches the schema. Fix the draft; do not add commentary."},
                    {"role": "user", "content": f"Schema:\n{json.dumps(p['model_cls'].model_json_schema())}\n\nDraft:\n{text}"}])
                out = self._validate(node, p["model_cls"], fixed)
            except Exception as exc:
                st["status"][node.id] = "failed"
                st["error"] = f"{node.id}: {exc}"
                self.save(st)
                await self.ctx.emit("node_failed", node.id, {"error": str(exc)})
                raise BridgeError(str(exc)) from exc
        usage = (st.get("usage") or {}).get(node.id, {})
        prep = (st.get("prepared") or {}).get(node.id, {})
        tokens = int(usage.get("tokens") or estimate_tokens(p["system"] + p["task"] + json.dumps(out)))
        metrics = {"tokens": tokens, "latency_s": round(time.time() - float(prep.get("t0", time.time())), 3), "model": usage.get("model", p["profile"]),
                   "cost": LLMSettings.cost(p["profile"], tokens, self.ctx.fx_rate), "framework": "n8n AI Agent", "model_calls": usage.get("calls", 0)}
        await self._succeed(st, node, out, metrics)
        return {"ok": True, "node_id": node.id}

    # ---- approvals -------------------------------------------------------
    async def op_approval_request(self, body: dict) -> dict:
        st = self.state()
        node = self.node(body["node_id"])
        self._guard(st, node)
        if st["status"].get(node.id) in ("succeeded", "failed"):
            return {"ok": True, "cached": True}
        cfg = node.config
        request = {"node_id": node.id, "name": node.name, "approver_role": cfg.get("approver_role"), "evidence": cfg.get("evidence"),
                   "sla_hours": cfg.get("sla_hours", 24)}
        st["pending"][node.id] = {"request": request, "resume_url": body.get("resume_url"), "execution_id": body.get("execution_id")}
        st["status"][node.id] = "approval"
        self.save(st)
        await self.ctx.emit("approval_requested", node.id, request)
        return {"ok": True, "node_id": node.id}

    async def op_approval_result(self, body: dict) -> dict:
        st = self.state()
        node = self.node(body["node_id"])
        if st["status"].get(node.id) == "succeeded":
            return {"ok": True, "approved": True, "cached": True}
        raw = body.get("decision") or {}
        if isinstance(raw, str):
            raw = json.loads(raw)
        d = Decision.model_validate(raw)
        st["pending"].pop(node.id, None)
        st["decisions"][node.id] = d.model_dump()
        await self.ctx.emit("approval_decided", node.id, d.model_dump())
        if d.decision == "Approved":
            await self._succeed(st, node, d.model_dump(), {"tokens": 0, "cost": 0})
            return {"ok": True, "approved": True}
        st["status"][node.id] = "failed"
        st["halted"] = f"{node.name} rejected by {d.by}" + (f": {d.comment}" if d.comment else "")
        st["log"].append(st["halted"])
        st["edge_active"].update(deactivate_outgoing(self.ctx.graph, node.id))
        await self.propagate_skips(st)
        return {"ok": True, "approved": False}
