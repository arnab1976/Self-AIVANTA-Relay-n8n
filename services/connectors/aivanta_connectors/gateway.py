"""MCP tool gateway: registry, permission checks, scopes, timeouts,
idempotency for external actions and trace logging (blueprint section 11).

If MCP_GATEWAY_URL is set, calls are forwarded as MCP `tools/call` JSON-RPC
requests to that gateway. Otherwise the built-in connectors below are used:
they work against AIVANTA's own data (uploaded RFPs, artifacts, snapshots)
and return clearly labelled sample data for systems that are not connected.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

import httpx

from .registry import ToolDefinition, load_registry
from .retrieval import hybrid_search


class ToolError(Exception):
    """Raised for policy violations or connector failures (non-retryable unless `transient`)."""

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


class ToolBackend(Protocol):
    """Data access the API layer provides to connectors. Always tenant + project scoped."""

    def read_document_text(self, tenant_id: str, project_id: str) -> dict: ...
    def project_metadata(self, tenant_id: str, project_id: str) -> dict: ...
    def project_chunks(self, tenant_id: str, project_id: str) -> list[dict]: ...
    def staff_availability(self, tenant_id: str) -> list[dict]: ...
    def idempotency_get(self, tenant_id: str, key: str) -> dict | None: ...
    def idempotency_put(self, tenant_id: str, key: str, run_id: str, node_id: str, tool_id: str, request: dict, response: dict) -> None: ...


@dataclass
class ToolContext:
    tenant_id: str
    project_id: str
    run_id: str
    node_id: str
    approved_tools: set[str]
    idempotency_prefix: str
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)


PATTERN_LIBRARY = [
    {"id": "pattern-modular-containers", "text": "Reference pattern: modular services on managed containers with managed PostgreSQL + pgvector, private object storage, SSO/OIDC and centralised logging.", "source": "Architecture standards §2"},
    {"id": "pattern-event-driven", "text": "Reference pattern: event-driven integration with a durable queue, idempotent consumers and dead-letter handling.", "source": "Architecture standards §4"},
    {"id": "pattern-data-residency", "text": "Data residency: deploy all customer data stores in the client's mandated region; replicate backups within the same jurisdiction.", "source": "Security standards §1.3"},
]


class ToolGateway:
    def __init__(self, backend: ToolBackend, registry: dict[str, ToolDefinition] | None = None):
        self.backend = backend
        self.registry = registry or load_registry()
        self.mcp_url = os.getenv("MCP_GATEWAY_URL")
        self.trace: list[dict] = []

    def describe(self, tool_id: str) -> ToolDefinition:
        if tool_id not in self.registry:
            raise ToolError(f"Tool '{tool_id}' is not registered.")
        return self.registry[tool_id]

    async def invoke(self, tool_id: str, operation: str, payload: dict[str, Any], ctx: ToolContext,
                     timeout_s: int | None = None) -> dict[str, Any]:
        tool = self.describe(tool_id)
        if tool_id not in ctx.approved_tools:
            raise ToolError(f"Tool '{tool_id}' is not approved for this tenant.")
        key = None
        if tool.external:
            key = f"{ctx.idempotency_prefix}:{ctx.node_id}:{tool_id}:{operation}"
            prior = self.backend.idempotency_get(ctx.tenant_id, key)
            if prior is not None:
                self._log(ctx, tool_id, operation, "replayed", key)
                return {**prior, "idempotent_replay": True}
        try:
            result = await asyncio.wait_for(self._dispatch(tool, operation, payload, ctx), timeout=timeout_s or tool.timeout_s)
        except asyncio.TimeoutError as exc:
            self._log(ctx, tool_id, operation, "timeout", key)
            raise ToolError(f"{tool_id}.{operation} timed out after {timeout_s or tool.timeout_s}s", transient=True) from exc
        result = {"status": "ok", "tool": tool_id, "operation": operation, "trace_id": ctx.trace_id, "data": result}
        if key:
            self.backend.idempotency_put(ctx.tenant_id, key, ctx.run_id, ctx.node_id, tool_id, {"operation": operation, "payload": payload}, result)
        self._log(ctx, tool_id, operation, "ok", key)
        return result

    def _log(self, ctx: ToolContext, tool_id: str, operation: str, status: str, key: str | None) -> None:
        self.trace.append({"trace_id": ctx.trace_id, "run_id": ctx.run_id, "node_id": ctx.node_id, "tool": tool_id,
                           "operation": operation, "status": status, "idempotency_key": key})

    async def _dispatch(self, tool: ToolDefinition, operation: str, payload: dict, ctx: ToolContext) -> dict:
        if self.mcp_url:
            return await self._mcp_call(tool, operation, payload, ctx)
        fn: Callable[[str, dict, ToolContext], Awaitable[dict]] = getattr(self, f"_t_{tool.id}", None)
        if fn is None:
            raise ToolError(f"No built-in connector for '{tool.id}'. Configure MCP_GATEWAY_URL.")
        return await fn(operation, payload, ctx)

    async def _mcp_call(self, tool: ToolDefinition, operation: str, payload: dict, ctx: ToolContext) -> dict:
        body = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "tools/call",
                "params": {"name": tool.id, "arguments": {"operation": operation, "payload": payload, "project_id": ctx.project_id,
                                                          "run_id": ctx.run_id, "credential_ref": tool.credential_ref}}}
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "X-AIVANTA-Tenant": ctx.tenant_id, "X-AIVANTA-Trace": ctx.trace_id}
        token = os.getenv("MCP_GATEWAY_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=tool.timeout_s) as client:
            resp = await client.post(self.mcp_url, json=body, headers=headers)
        if resp.status_code >= 500:
            raise ToolError(f"MCP gateway error {resp.status_code}", transient=True)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise ToolError(f"MCP error: {data['error'].get('message')}")
        content = data.get("result", {}).get("content", [])
        text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        try:
            return json.loads(text) if text else data.get("result", {})
        except json.JSONDecodeError:
            return {"text": text}

    # ---- built-in connectors ------------------------------------------------
    async def _t_document_reader(self, op, payload, ctx):
        return self.backend.read_document_text(ctx.tenant_id, ctx.project_id)

    async def _t_ocr_parser(self, op, payload, ctx):
        doc = self.backend.read_document_text(ctx.tenant_id, ctx.project_id)
        text = doc.get("text", "")
        headings = [ln.strip() for ln in text.splitlines() if ln.strip() and (ln.strip()[:1].isdigit() or ln.isupper()) and len(ln) < 90]
        return {"text": text, "sections_detected": len(headings), "ocr_pages": 0 if text.strip() else doc.get("pages", 0),
                "note": None if text.strip() else "No text layer found; route to an OCR service."}

    async def _t_object_store(self, op, payload, ctx):
        doc = self.backend.read_document_text(ctx.tenant_id, ctx.project_id)
        return {k: v for k, v in doc.items() if k != "text"} | {"available": bool(doc.get("filename"))}

    async def _t_template_renderer(self, op, payload, ctx):
        return {"rendered": payload.get("artifacts", []), "formats": ["docx", "pdf", "xlsx"]}

    async def _t_sharepoint_search(self, op, payload, ctx):
        query = payload.get("query") or "reference architecture"
        chunks = self.backend.project_chunks(ctx.tenant_id, ctx.project_id)
        hits = hybrid_search(query, chunks, top_k=int(payload.get("top_k", 4)))
        return {"query": query, "results": [{"text": h["text"][:400], "source": h.get("source"), "score": h["score"]} for h in hits] + PATTERN_LIBRARY[:2]}

    async def _t_crm_opportunity(self, op, payload, ctx):
        return self.backend.project_metadata(ctx.tenant_id, ctx.project_id)

    async def _t_hrms_availability(self, op, payload, ctx):
        url = os.getenv("HRMS_URL")
        if url:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.get(f"{url.rstrip('/')}/availability", headers={"Authorization": f"Bearer {os.getenv('HRMS_TOKEN', '')}"})
                r.raise_for_status()
                return {"people": r.json(), "verified": True}
        return {"people": self.backend.staff_availability(ctx.tenant_id), "verified": False,
                "note": "Sample availability; connect HRMS_URL for authorised data."}

    async def _t_jira_backlog(self, op, payload, ctx):
        url, token, project = os.getenv("JIRA_URL"), os.getenv("JIRA_TOKEN"), os.getenv("JIRA_PROJECT_KEY", "AIV")
        epics = payload.get("epics") or ["Discovery & BRD", "Architecture & setup", "Build", "UAT & rollout"]
        if url and token:
            created = []
            async with httpx.AsyncClient(timeout=60) as c:
                for e in epics:
                    r = await c.post(f"{url.rstrip('/')}/rest/api/3/issue", headers={"Authorization": f"Bearer {token}"},
                                     json={"fields": {"project": {"key": project}, "summary": e, "issuetype": {"name": "Epic"}}})
                    r.raise_for_status()
                    created.append(r.json().get("key"))
            return {"created": created}
        digest = hashlib.sha1(ctx.run_id.encode()).hexdigest()[:3].upper()
        return {"created": [f"{project}-{digest}{i}" for i in range(1, len(epics) + 1)], "note": "Sample keys; set JIRA_URL and JIRA_TOKEN to create real issues."}

    async def _t_cloud_pricing(self, op, payload, ctx):
        from aivanta_pricing.cloud import load_snapshot, snapshot_age_days
        snap = load_snapshot()
        return {"snapshot_id": snap["snapshot_id"], "effective_date": snap["effective_date"], "age_days": snapshot_age_days(snap),
                "providers": list(snap["providers"].keys()), "illustrative": snap.get("illustrative", True)}

    async def _t_email_send(self, op, payload, ctx):
        raise ToolError("email_send is not configured. Connect the M365 mail connector through the MCP gateway.")
