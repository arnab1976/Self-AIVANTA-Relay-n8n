"""n8n ⇄ AIVANTA bridge and the OpenAI-compatible model gateway.

Only n8n calls these endpoints. They are authenticated with the shared
bridge token (``AIVANTA_BRIDGE_TOKEN``), which n8n holds in two credentials:

* **AIVANTA Bridge** (Header Auth, ``X-Aivanta-Bridge-Token``) — used by every
  HTTP Request node in compiled workflows and by the Trigger webhook.
* **AIVANTA Model Gateway** (OpenAI API, base URL ``<api>/gateway/v1``) — used by
  the OpenAI Chat Model sub-node of each AI Agent node.

Keep ``/internal`` and ``/gateway`` on the private network (n8n → API); do
not route them through the public load balancer.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
import uuid

from aivanta_runtime import get_adapter
from aivanta_runtime.steps import BridgeError, StepExecutor
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..db import session_scope
from ..models import ExecutionRun, Tenant
from ..services.run_service import build_context

router = APIRouter(tags=["n8n bridge (internal)"])
_locks: dict[str, asyncio.Lock] = {}


def _token() -> str:
    return os.getenv("AIVANTA_BRIDGE_TOKEN", "change-me")


def _authorize(request: Request) -> None:
    supplied = request.headers.get("X-Aivanta-Bridge-Token") or ""
    auth = request.headers.get("Authorization", "")
    if not supplied and auth.lower().startswith("bearer "):
        supplied = auth[7:]
    if not supplied or not hmac.compare_digest(supplied.encode(), _token().encode()):
        raise HTTPException(401, "Invalid bridge token")


async def _executor(run_id: str) -> StepExecutor:
    if not run_id:
        raise HTTPException(422, "run_id is required")
    try:
        ctx = await asyncio.to_thread(build_context, run_id)
    except AttributeError as exc:  # unknown run id
        raise HTTPException(404, f"Unknown run {run_id}") from exc
    return StepExecutor(ctx, getattr(get_adapter(), "agent_mode", "native"))


@router.post("/internal/n8n/{op}")
async def bridge(op: str, request: Request):
    _authorize(request)
    body = await request.json()
    run_id = str(body.get("run_id") or "")
    ex = await _executor(run_id)
    async with _locks.setdefault(run_id, asyncio.Lock()):
        try:
            return await ex.handle(op, body)
        except BridgeError as exc:
            return JSONResponse({"error": str(exc), "transient": exc.transient}, status_code=exc.status_code)


# ---------------------------------------------------------------------------
# OpenAI-compatible model gateway for n8n AI Agent nodes
# ---------------------------------------------------------------------------
PROFILES = ["enterprise-reasoning", "enterprise-fast", "local-open-weight"]


@router.get("/gateway/v1/models")
async def models(request: Request):
    _authorize(request)
    return {"object": "list", "data": [{"id": p, "object": "model", "owned_by": "aivanta"} for p in PROFILES]}


def _check_allowlist(run_id: str, node_id: str) -> str:
    with session_scope() as db:
        run = db.get(ExecutionRun, run_id)
        if run is None:
            raise HTTPException(404, f"Unknown run {run_id}")
        node = next((n for n in run.graph_snapshot.get("nodes", []) if n["id"] == node_id), None)
        if node is None or node["type"] != "agent":
            raise HTTPException(404, f"{node_id} is not an agent node of run {run_id}")
        profile = (node.get("config") or {}).get("model_profile") or "enterprise-fast"
        tenant = db.get(Tenant, run.tenant_id)
        if profile not in (tenant.allowed_models or []):
            raise HTTPException(403, f"Model profile '{profile}' is not allowed for tenant {tenant.code}")
        return profile


@router.post("/gateway/v1/chat/completions")
async def chat_completions(request: Request):
    _authorize(request)
    body = await request.json()
    model = str(body.get("model", ""))
    parts = model.split(":")
    if len(parts) != 3 or parts[0] != "aivanta":
        raise HTTPException(422, "model must be 'aivanta:<run_id>:<node_id>' (set by the compiled workflow)")
    _, run_id, node_id = parts
    profile = await asyncio.to_thread(_check_allowlist, run_id, node_id)
    ex = await _executor(run_id)
    messages = [m for m in body.get("messages", []) if isinstance(m, dict)]
    async with _locks.setdefault(run_id, asyncio.Lock()):
        try:
            content, usage, provider_model = await ex.chat(node_id, messages)
        except BridgeError as exc:
            return JSONResponse({"error": {"message": str(exc), "type": "aivanta_bridge"}}, status_code=exc.status_code)
    cid, created = f"chatcmpl-{uuid.uuid4().hex[:20]}", int(time.time())
    if body.get("stream"):
        def sse():
            chunk = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": profile,
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}]}
            yield f"data: {json.dumps(chunk)}\n\n"
            done = {**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage}
            yield f"data: {json.dumps(done)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(sse(), media_type="text/event-stream")
    return {"id": cid, "object": "chat.completion", "created": created, "model": profile, "system_fingerprint": provider_model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop", "logprobs": None}],
            "usage": usage}
