"""Clients for the n8n runtime.

* ``RestN8n`` talks to a real n8n instance (self-hosted, queue mode) through
  its public REST API (`/api/v1`, header ``X-N8N-API-KEY``) and its webhooks.
* ``EmulatedN8n`` interprets the same compiled workflow JSON in-process. It
  covers exactly the node types the AIVANTA compiler emits (Webhook, HTTP
  Request to the bridge, Switch, IF, Wait, Merge, AI Agent + Chat Model) and
  follows n8n's v1 execution order (depth-first, output 0 first). It exists
  so the runtime contract tests, CI and a laptop demo work without an n8n
  server. It is single-process only: use ``N8N_MODE=rest`` for real deployments.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from .n8n_compiler import BRIDGE_CREDENTIAL, GATEWAY_CREDENTIAL, TRIGGER
from .steps import BridgeError, StepExecutor

log = logging.getLogger("aivanta.n8n")


class N8nError(RuntimeError):
    pass


class N8nClient(Protocol):
    kind: str

    async def setup(self) -> dict[str, str]: ...
    async def deploy(self, workflow: dict[str, Any], tenant_tag: str) -> str: ...
    async def trigger(self, workflow: dict[str, Any], payload: dict[str, Any], executor: StepExecutor) -> None: ...
    async def resume(self, resume_url: str, body: dict[str, Any], executor: StepExecutor) -> None: ...
    async def retry(self, execution_id: str, executor: StepExecutor) -> str: ...
    async def status(self, execution_id: str) -> dict[str, Any]: ...
    async def stop(self, execution_id: str) -> None: ...
    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Real n8n
# ---------------------------------------------------------------------------
@dataclass
class RestSettings:
    api_url: str = "http://localhost:5678/api/v1"
    api_key: str = ""
    webhook_url: str = "http://localhost:5678"
    bridge_url: str = "http://localhost:8000"
    bridge_token: str = "change-me"
    bridge_credential_id: str = ""
    gateway_credential_id: str = ""
    credentials_cache: str = ".n8n-credentials.json"
    project_id: str = ""        # n8n Enterprise projects: deploy each tenant's workflows into its own project

    @classmethod
    def from_env(cls, prefix: str = "N8N_") -> "RestSettings":
        g = lambda k, d="": os.getenv(prefix + k, d)  # noqa: E731
        return cls(api_url=g("API_URL", "http://localhost:5678/api/v1"), api_key=g("API_KEY"), webhook_url=g("WEBHOOK_URL", "http://localhost:5678"),
                   bridge_url=os.getenv("AIVANTA_BRIDGE_URL", "http://localhost:8000"), bridge_token=os.getenv("AIVANTA_BRIDGE_TOKEN", "change-me"),
                   bridge_credential_id=g("BRIDGE_CREDENTIAL_ID"), gateway_credential_id=g("GATEWAY_CREDENTIAL_ID"),
                   credentials_cache=g("CREDENTIALS_CACHE", ".n8n-credentials.json"), project_id=g("PROJECT_ID"))


class RestN8n:
    kind = "rest"

    def __init__(self, s: RestSettings | None = None):
        self.s = s or RestSettings.from_env()
        self.http = httpx.AsyncClient(base_url=self.s.api_url.rstrip("/"), headers={"X-N8N-API-KEY": self.s.api_key, "Accept": "application/json"}, timeout=30)
        self._tags: dict[str, str] = {}

    async def close(self) -> None:
        await self.http.aclose()

    async def _req(self, method: str, path: str, **kw) -> Any:
        r = await self.http.request(method, path, **kw)
        if r.status_code >= 400:
            raise N8nError(f"n8n {method} {path} -> HTTP {r.status_code}: {r.text[:400]}")
        return r.json() if r.content else {}

    # credentials: AIVANTA never stores tenant secrets in n8n; it only needs two service credentials
    async def setup(self) -> dict[str, str]:
        if not self.s.api_key:
            raise N8nError("N8N_API_KEY is not set. Create an API key in n8n (Settings → n8n API) or run `make n8n-bootstrap`.")
        cache = Path(self.s.credentials_cache)
        cached = json.loads(cache.read_text()) if cache.exists() else {}
        if not self.s.bridge_credential_id:
            self.s.bridge_credential_id = cached.get("bridge") or (await self._req("POST", "/credentials", json={
                "name": BRIDGE_CREDENTIAL, "type": "httpHeaderAuth", "data": {"name": "X-Aivanta-Bridge-Token", "value": self.s.bridge_token}}))["id"]
        if not self.s.gateway_credential_id:
            self.s.gateway_credential_id = cached.get("gateway") or (await self._req("POST", "/credentials", json={
                "name": GATEWAY_CREDENTIAL, "type": "openAiApi",
                "data": {"apiKey": self.s.bridge_token, "url": f"{self.s.bridge_url.rstrip('/')}/gateway/v1", "header": False}}))["id"]
        ids = {"bridge": self.s.bridge_credential_id, "gateway": self.s.gateway_credential_id}
        try:
            cache.write_text(json.dumps(ids))
        except OSError:
            pass
        return ids

    async def _tag(self, name: str) -> str:
        if name in self._tags:
            return self._tags[name]
        rows = (await self._req("GET", "/tags", params={"limit": 250})).get("data", [])
        tid = next((t["id"] for t in rows if t["name"] == name), None) or (await self._req("POST", "/tags", json={"name": name}))["id"]
        self._tags[name] = tid
        return tid

    async def deploy(self, workflow: dict[str, Any], tenant_tag: str) -> str:
        existing = (await self._req("GET", "/workflows", params={"name": workflow["name"], "limit": 10})).get("data", [])
        wid = next((w["id"] for w in existing if w["name"] == workflow["name"]), None)
        if wid is None:
            body = {k: workflow[k] for k in ("name", "nodes", "connections", "settings")}
            wid = (await self._req("POST", "/workflows", json=body))["id"]
            if self.s.project_id:
                await self._req("PUT", f"/workflows/{wid}/transfer", json={"destinationProjectId": self.s.project_id})
            try:
                await self._req("PUT", f"/workflows/{wid}/tags", json=[{"id": await self._tag(t)} for t in ["aivanta", tenant_tag]])
            except N8nError as exc:  # tags are a convenience, never a reason to fail a run
                log.warning("tagging workflow %s failed: %s", wid, exc)
        await self._req("POST", f"/workflows/{wid}/activate")
        return str(wid)

    async def trigger(self, workflow: dict[str, Any], payload: dict[str, Any], executor: StepExecutor) -> None:
        path = workflow["meta"]["aivanta"]["webhook_path"]
        url = f"{self.s.webhook_url.rstrip('/')}/webhook/{path}"
        for attempt in range(5):  # a freshly activated webhook can take a moment to register in queue mode
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(url, json=payload, headers={"X-Aivanta-Bridge-Token": self.s.bridge_token})
            if r.status_code < 400:
                return
            if r.status_code != 404:
                break
            await asyncio.sleep(0.5 * (attempt + 1))
        raise N8nError(f"n8n webhook {url} -> HTTP {r.status_code}: {r.text[:300]}")

    async def resume(self, resume_url: str, body: dict[str, Any], executor: StepExecutor) -> None:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(resume_url, json=body)
        if r.status_code >= 400:
            raise N8nError(f"n8n resume {resume_url} -> HTTP {r.status_code}: {r.text[:300]}")

    async def retry(self, execution_id: str, executor: StepExecutor) -> str:
        res = await self._req("POST", f"/executions/{execution_id}/retry", json={"loadWorkflow": False})
        return str(res.get("id") or execution_id)

    async def status(self, execution_id: str) -> dict[str, Any]:
        ex = await self._req("GET", f"/executions/{execution_id}", params={"includeData": "true"})
        err = (((ex.get("data") or {}).get("resultData") or {}).get("error") or {})
        return {"status": ex.get("status") or ("success" if ex.get("finished") else "running"), "error": err.get("message"),
                "last_node": ((ex.get("data") or {}).get("resultData") or {}).get("lastNodeExecuted")}

    async def stop(self, execution_id: str) -> None:
        try:
            await self._req("POST", f"/executions/{execution_id}/stop")
        except N8nError as exc:
            log.info("stop %s: %s", execution_id, exc)


# ---------------------------------------------------------------------------
# In-process emulator
# ---------------------------------------------------------------------------
_BODY_FIELD = re.compile(r"(\w+):\s*([^,}]+(?:\([^)]*\)[^,}]*)?)")


@dataclass
class _Exec:
    id: str
    wf: dict[str, Any]
    payload: dict[str, Any]
    stack: list[tuple[str, int, list[dict]]] = field(default_factory=list)   # (node, input index, items)
    merges: dict[str, dict[int, list[dict]]] = field(default_factory=dict)
    outputs: dict[str, list[dict]] = field(default_factory=dict)              # last output items per node (for $('Node'))
    status: str = "new"
    error: str | None = None
    paused_at: str | None = None
    failed: tuple[str, int, list[dict]] | None = None


class EmulatedN8n:
    kind = "emulated"
    _executions: dict[str, _Exec] = {}

    async def setup(self) -> dict[str, str]:
        return {"bridge": "emulated", "gateway": "emulated"}

    async def close(self) -> None:
        pass

    async def deploy(self, workflow: dict[str, Any], tenant_tag: str) -> str:
        return f"emu-wf-{workflow['meta']['aivanta']['graph_hash']}"

    async def trigger(self, workflow: dict[str, Any], payload: dict[str, Any], executor: StepExecutor) -> None:
        ex = _Exec(id=f"emu-{uuid.uuid4().hex[:10]}", wf=workflow, payload=payload)
        self._executions[ex.id] = ex
        trig = self._node(ex, TRIGGER)
        ex.stack.append((trig["name"], 0, [{"json": {"body": payload, "headers": {}}}]))
        await self._run(ex, executor)

    async def resume(self, resume_url: str, body: dict[str, Any], executor: StepExecutor) -> None:
        exec_id = resume_url.split("emulated://", 1)[1].split("/", 1)[0]
        ex = self._executions.get(exec_id)
        if ex is None or ex.status != "waiting":
            raise N8nError(f"No waiting emulated execution {exec_id}")
        node = ex.paused_at
        ex.paused_at, ex.status = None, "running"
        out = [{"json": {"body": body, "headers": {}, "query": {}}}]
        ex.outputs[node] = out
        self._push_children(ex, node, [out])
        await self._run(ex, executor)

    async def retry(self, execution_id: str, executor: StepExecutor) -> str:
        ex = self._executions.get(execution_id)
        if ex is None or ex.failed is None:
            raise N8nError(f"Execution {execution_id} has nothing to retry")
        new_id = f"emu-{uuid.uuid4().hex[:10]}"
        ex.id = new_id
        self._executions[new_id] = ex
        ex.stack.append(ex.failed)
        ex.failed, ex.error, ex.status = None, None, "running"
        await self._run(ex, executor)
        return new_id

    async def status(self, execution_id: str) -> dict[str, Any]:
        ex = self._executions.get(execution_id)
        if ex is None:
            return {"status": "unknown", "error": None}
        return {"status": ex.status, "error": ex.error, "last_node": ex.paused_at}

    async def stop(self, execution_id: str) -> None:
        ex = self._executions.get(execution_id)
        if ex:
            ex.status, ex.stack = "canceled", []

    # ---- interpreter -----------------------------------------------------
    @staticmethod
    def _node(ex: _Exec, name: str) -> dict:
        return next(n for n in ex.wf["nodes"] if n["name"] == name)

    def _push_children(self, ex: _Exec, name: str, outputs: list[list[dict]]) -> None:
        conns = ex.wf["connections"].get(name, {}).get("main", [])
        todo = []
        for out_idx, items in enumerate(outputs):
            if not items or out_idx >= len(conns):
                continue
            for target in conns[out_idx]:
                todo.append((target["node"], target["index"], items))
        for t in reversed(todo):      # depth-first, output 0 first (n8n v1 execution order)
            ex.stack.append(t)

    def _inputs_of(self, ex: _Exec, name: str) -> set[int]:
        idx = set()
        for src in ex.wf["connections"].values():
            for outs in src.get("main", []):
                for t in outs:
                    if t["node"] == name:
                        idx.add(t["index"])
        return idx

    async def _run(self, ex: _Exec, executor: StepExecutor) -> None:
        ex.status = "running"
        while ex.stack:
            name, inp, items = ex.stack.pop()
            node = self._node(ex, name)
            typ = node["type"]
            if typ.endswith(".merge"):
                buf = ex.merges.setdefault(name, {})
                buf[inp] = items
                if set(buf) >= self._inputs_of(ex, name):
                    merged = [i for k in sorted(buf) for i in buf[k]]
                    ex.merges.pop(name)
                    ex.outputs[name] = merged
                    self._push_children(ex, name, [merged])
                continue
            if typ.endswith(".wait"):
                ex.status, ex.paused_at = "waiting", name
                return
            try:
                outputs = await self._execute(ex, node, items, executor)
            except Exception as exc:
                ex.status, ex.error, ex.failed = "error", f"{name}: {exc}", (name, inp, items)
                ex.stack = []
                return
            first = next((o for o in outputs if o), [])
            ex.outputs[name] = first
            self._push_children(ex, name, outputs)
        ex.status = "success"

    async def _execute(self, ex: _Exec, node: dict, items: list[dict], executor: StepExecutor) -> list[list[dict]]:
        typ, p = node["type"], node.get("parameters", {})
        item = items[0]["json"] if items else {}
        if typ.endswith(".webhook"):
            return [items]
        if typ.endswith(".httpRequest"):
            op = p["url"].rsplit("/internal/n8n/", 1)[1]
            body = self._body(ex, p.get("jsonBody", ""), item)
            tries = int(node.get("maxTries", 1)) if node.get("retryOnFail") else 1
            last: Exception | None = None
            for _ in range(tries):
                try:
                    return [[{"json": await executor.handle(op, body)}]]
                except BridgeError as exc:
                    last = exc
            raise N8nError(f"HTTP {last.status_code}: {last}")  # type: ignore[union-attr]
        if typ.endswith(".switch"):
            rules = p["rules"]["values"]
            outs: list[list[dict]] = [[] for _ in rules]
            for i, r in enumerate(rules):
                if r["conditions"]["conditions"][0]["rightValue"] == item.get("route"):
                    outs[i] = items
                    break
            return outs
        if typ.endswith(".if"):
            return [items, []] if item.get("approved") is True else [[], items]
        if typ.endswith("langchain.agent"):
            model = self._model_for(ex, node["name"])
            messages = [{"role": "system", "content": item.get("system", "")}, {"role": "user", "content": item.get("task", "")}]
            tries = int(node.get("maxTries", 1)) if node.get("retryOnFail") else 1
            for attempt in range(tries):
                try:
                    content, _, _ = await executor.chat(model.split(":")[-1], messages)
                    return [[{"json": {"output": content}}]]
                except BridgeError:
                    if attempt == tries - 1:
                        raise
        return [items]

    def _model_for(self, ex: _Exec, agent_name: str) -> str:
        for src, outs in ex.wf["connections"].items():
            for t in (outs.get("ai_languageModel") or [[]])[0]:
                if t["node"] == agent_name:
                    expr = self._node(ex, src)["parameters"]["model"]["value"]
                    prep = re.search(r"\$\('([^']+)'\)", expr).group(1)
                    return ex.outputs[prep][0]["json"]["model"]
        raise N8nError(f"No chat model attached to {agent_name}")

    def _body(self, ex: _Exec, expr: str, item: dict) -> dict[str, Any]:
        inner = expr[expr.index("({") + 2: expr.rindex("})")]
        out: dict[str, Any] = {}
        for key, val in _BODY_FIELD.findall(inner):
            val = val.strip()
            if val.startswith(f"$('{TRIGGER}')"):
                out[key] = ex.payload.get("run_id")
            elif val == "$execution.id":
                out[key] = ex.id
            elif val == "$execution.resumeUrl":
                out[key] = f"emulated://{ex.id}/resume"
            elif val.startswith("$json."):
                out[key] = item.get(val[len("$json."):])
            else:
                out[key] = json.loads(val)
        return out
