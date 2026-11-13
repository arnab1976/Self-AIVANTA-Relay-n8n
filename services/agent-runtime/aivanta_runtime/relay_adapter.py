"""AIVANTA Relay runtime: the canvas runs as an n8n workflow.

Lifecycle
---------
start          compile the canvas → deploy (one immutable n8n workflow per published graph hash,
               tagged with the tenant) → trigger its webhook with the run id → wait until the
               execution finishes or pauses on a Wait node.
resume         POST each decided approval to the resume URL n8n handed to AIVANTA, then wait again.
retry_failed   ask n8n to retry the failed execution from the failed node. Bridge steps are
               idempotent, so completed work and external side effects are never repeated.

All run state (node status, outputs, metrics, pending approvals, the n8n execution id) is written
by the bridge into the AIVANTA run record. The adapter only reads it, which is why any API
replica or worker can serve a run.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from aivanta_graph import CanvasGraph

from .contract import Decision, RunContext, RunOutcome, RuntimeAdapter
from .n8n_client import EmulatedN8n, N8nError, RestN8n
from .n8n_compiler import CompileOptions, compile_workflow, node_map
from .steps import StepExecutor, empty_state

TERMINAL = {"success", "error", "canceled", "crashed"}


def _tenant_instances() -> dict[str, dict[str, str]]:
    """Optional dedicated n8n per tenant: N8N_TENANT_INSTANCES={"<tenant_id>": {"api_url":..,"api_key_env":..,"webhook_url":..}}"""
    try:
        return json.loads(os.getenv("N8N_TENANT_INSTANCES", "") or "{}")
    except json.JSONDecodeError:
        return {}


class RelayAdapter(RuntimeAdapter):
    name = "relay"
    framework = "n8n"

    def __init__(self, mode: str | None = None):
        self.mode = (mode or os.getenv("N8N_MODE", "emulated")).lower()
        self.agent_mode = os.getenv("RELAY_AGENT_MODE", "native").lower()
        self.bridge_url = os.getenv("AIVANTA_BRIDGE_URL", "http://localhost:8000")
        self.poll_s = float(os.getenv("N8N_POLL_SECONDS", "0.5"))
        self.timeout_s = float(os.getenv("N8N_RUN_TIMEOUT_SECONDS", "1800"))
        self._clients: dict[str, Any] = {}
        self._creds: dict[str, dict[str, str]] = {}

    # ---- clients ---------------------------------------------------------
    def client(self, tenant_id: str | None = None):
        if self.mode == "emulated":
            return self._clients.setdefault("emulated", EmulatedN8n())
        key = tenant_id if tenant_id in _tenant_instances() else "shared"
        if key not in self._clients:
            from .n8n_client import RestSettings
            s = RestSettings.from_env()
            if key != "shared":
                inst = _tenant_instances()[key]
                s.api_url, s.webhook_url = inst.get("api_url", s.api_url), inst.get("webhook_url", s.webhook_url)
                s.api_key = os.getenv(inst.get("api_key_env", ""), s.api_key)
                s.credentials_cache = f".n8n-credentials-{key}.json"
                s.bridge_credential_id = inst.get("bridge_credential_id", "")
                s.gateway_credential_id = inst.get("gateway_credential_id", "")
            self._clients[key] = RestN8n(s)
        return self._clients[key]

    async def _creds_for(self, tenant_id: str) -> dict[str, str]:
        c = self.client(tenant_id)
        key = getattr(c, "kind", "x") + str(id(c))
        if key not in self._creds:
            self._creds[key] = await c.setup()
        return self._creds[key]

    def framework_version(self) -> str:
        try:
            core = f"aivanta-relay {version('aivanta-relay')}"
        except PackageNotFoundError:
            core = "aivanta-relay"
        target = os.getenv("N8N_VERSION", "2.x")
        return f"n8n {target} ({'emulated in-process' if self.mode == 'emulated' else 'REST + webhooks'}, agents: {self.agent_mode}) · {core}"

    async def setup(self) -> None:
        if self.mode == "rest":
            try:
                await self._creds_for("shared")
            except Exception as exc:  # the API must still start so admins can fix configuration
                import logging
                logging.getLogger("aivanta.n8n").error("n8n setup failed: %s", exc)

    async def close(self) -> None:
        for c in self._clients.values():
            await c.close()

    # ---- compilation -----------------------------------------------------
    def options(self, graph: CanvasGraph, tenant_id: str, creds: dict[str, str] | None = None) -> CompileOptions:
        h = graph.content_hash()
        creds = creds or {}
        return CompileOptions(bridge_url=self.bridge_url, agent_mode=self.agent_mode, bridge_credential_id=creds.get("bridge", "aivanta-bridge"),
                              gateway_credential_id=creds.get("gateway", "aivanta-gateway"), webhook_path=f"aivanta/{tenant_id[:12]}/{h}",
                              workflow_name=f"AIVANTA · {tenant_id[:12]} · {h}", tags=["aivanta", f"tenant-{tenant_id[:12]}"])

    def export(self, graph: CanvasGraph) -> dict[str, Any]:
        wf = compile_workflow(graph, self.options(graph, "tenant"))
        wf.pop("meta", None)
        return {"format": "n8n-workflow", "runtime": "n8n", "content": wf,
                "note": "Import in n8n: Workflows → Import from file. Credentials 'AIVANTA Bridge' (Header Auth) and 'AIVANTA Model Gateway' "
                        "(OpenAI, base URL = AIVANTA /gateway/v1) must exist; AIVANTA creates them automatically in N8N_MODE=rest."}

    # ---- lifecycle -------------------------------------------------------
    def _executor(self, ctx: RunContext) -> StepExecutor:
        return StepExecutor(ctx, self.agent_mode)

    def _state(self, ctx: RunContext) -> dict[str, Any]:
        base = empty_state()
        base.update(ctx.load_state() or {})
        return base

    async def start(self, ctx: RunContext) -> RunOutcome:
        creds = await self._creds_for(ctx.tenant_id)
        wf = compile_workflow(ctx.graph, self.options(ctx.graph, ctx.tenant_id, creds))
        client = self.client(ctx.tenant_id)
        try:
            wid = await client.deploy(wf, f"tenant-{ctx.tenant_id[:12]}")
        except N8nError as exc:
            return RunOutcome(status="failed", error=f"n8n deploy failed: {exc}")
        st = self._state(ctx)
        st["n8n"] = {"workflow_id": wid, "workflow_name": wf["name"], "webhook_path": wf["meta"]["aivanta"]["webhook_path"],
                     "mode": self.mode, "agent_mode": self.agent_mode, "node_map": node_map(wf), "executions": []}
        ctx.save_state(st)
        await ctx.emit("run_started", None, {"runtime": self.framework, "version": self.framework_version(), "graph_version": ctx.graph_version,
                                             "n8n_workflow_id": wid, "n8n_workflow": wf["name"]})
        try:
            await client.trigger(wf, {"run_id": ctx.run_id, "tenant_id": ctx.tenant_id, "project_id": ctx.project.get("id"),
                                      "graph_version": ctx.graph_version}, self._executor(ctx))
        except N8nError as exc:
            return RunOutcome(status="failed", error=f"n8n trigger failed: {exc}")
        return await self._settle(ctx)

    async def resume(self, ctx: RunContext, decisions: dict[str, Decision]) -> RunOutcome:
        st = self._state(ctx)
        todo = {nid: d for nid, d in decisions.items() if nid in st["pending"]}
        if not todo:
            return await self._outcome(ctx, await self._exec_status(ctx))
        await ctx.emit("run_resumed", None, {"reason": "approval", "nodes": list(todo)})
        client = self.client(ctx.tenant_id)
        outcome: RunOutcome | None = None
        while todo:
            # n8n pauses on one Wait node at a time. Parallel approvals decided together are fed in turn:
            # each resume lets n8n reach the next Wait, which may already have a decision.
            for nid, d in todo.items():
                url = st["pending"][nid].get("resume_url")
                if not url:
                    return RunOutcome(status="failed", error=f"No n8n resume URL recorded for {nid}")
                try:
                    await client.resume(url, d.model_dump(), self._executor(ctx))
                except N8nError as exc:
                    return RunOutcome(status="failed", error=str(exc))
                outcome = await self._settle(ctx)
                break
            st = self._state(ctx)
            todo = {nid: d for nid, d in decisions.items() if nid in st["pending"]}
        return outcome or await self._settle(ctx)

    async def retry_failed(self, ctx: RunContext) -> RunOutcome:
        st = self._state(ctx)
        exec_id = st["n8n"].get("execution_id")
        if not exec_id:
            return await self.start(ctx)
        await ctx.emit("run_resumed", None, {"reason": "retry_failed", "n8n_execution": exec_id})
        st["error"] = None
        for nid, s in list(st["status"].items()):
            if s == "failed" and nid not in st["decisions"]:
                st["status"][nid] = "pending"
        ctx.save_state(st)
        try:
            new_id = await self.client(ctx.tenant_id).retry(exec_id, self._executor(ctx))
        except N8nError as exc:
            return RunOutcome(status="failed", error=str(exc))
        st = self._state(ctx)
        st["n8n"]["execution_id"] = new_id
        st["n8n"].setdefault("executions", []).append(new_id)
        ctx.save_state(st)
        return await self._settle(ctx)

    # ---- waiting and outcome ----------------------------------------------
    async def _exec_status(self, ctx: RunContext) -> dict[str, Any]:
        exec_id = self._state(ctx)["n8n"].get("execution_id")
        if not exec_id:
            return {"status": "unknown"}
        try:
            return await self.client(ctx.tenant_id).status(exec_id)
        except N8nError as exc:
            return {"status": "unknown", "error": str(exc)}

    async def _settle(self, ctx: RunContext, quiet: bool = False) -> RunOutcome:
        deadline = time.monotonic() + self.timeout_s
        seen_exec = time.monotonic() + 60
        while True:
            st = self._state(ctx)
            ex = await self._exec_status(ctx)
            s = ex.get("status")
            if s in TERMINAL or (s == "waiting" and st["pending"]):
                break
            if ctx.is_cancelled():
                if st["n8n"].get("execution_id"):
                    await self.client(ctx.tenant_id).stop(st["n8n"]["execution_id"])
                ex = {"status": "canceled"}
                break
            if s == "unknown" and not st["n8n"].get("execution_id") and time.monotonic() > seen_exec:
                ex = {"status": "error", "error": "n8n never started the execution (check the webhook URL and the AIVANTA Bridge credential)"}
                break
            if time.monotonic() > deadline:
                ex = {"status": "error", "error": f"timed out after {self.timeout_s:.0f}s waiting for n8n"}
                break
            await asyncio.sleep(self.poll_s)
        return await self._outcome(ctx, ex, quiet=quiet)

    async def _outcome(self, ctx: RunContext, ex: dict[str, Any], quiet: bool = False) -> RunOutcome:
        st = self._state(ctx)
        status, outputs, metrics = dict(st["status"]), st["outputs"], st["metrics"]
        totals = {"tokens": sum(int(m.get("tokens", 0)) for m in metrics.values()), "cost": round(sum(float(m.get("cost", 0)) for m in metrics.values()), 4),
                  "n8n_execution": st["n8n"].get("execution_id"), "n8n_workflow": st["n8n"].get("workflow_id")}
        pending = [p["request"] for p in st["pending"].values()]
        s = ex.get("status")
        if ctx.is_cancelled() or s == "canceled":
            return RunOutcome(status="cancelled", node_status=status, outputs=outputs, metrics=totals, error="Cancelled")
        if pending and s == "waiting":
            return RunOutcome(status="awaiting_approval", node_status=status, outputs=outputs, pending_approvals=pending, metrics=totals)
        if s not in TERMINAL:
            return RunOutcome(status="failed", node_status=status, outputs=outputs, metrics=totals, error=ex.get("error") or f"n8n execution status '{s}'")
        # terminal: every node n8n never reached was on an unchosen or stopped branch
        if not quiet:
            for n in ctx.graph.nodes:
                if status.get(n.id) in (None, "pending", "running"):
                    if status.get(n.id) is None or status.get(n.id) == "pending":
                        status[n.id] = "skipped"
                        await ctx.emit("node_skipped", n.id, {})
            st["status"] = status
            ctx.save_state(st)
        ok = s == "success" and not st.get("halted") and any(status.get(n.id) == "succeeded" for n in ctx.graph.nodes if n.type == "end")
        if ok:
            return RunOutcome(status="succeeded", node_status=status, outputs=outputs, metrics=totals)
        error = st.get("halted") or st.get("error") or ex.get("error") or "Run ended without reaching an End node"
        return RunOutcome(status="failed", node_status=status, outputs=outputs, metrics=totals, error=error)
