"""Execution runs: start, observe (events + SSE), cancel, retry from failure, replay."""
from __future__ import annotations

import asyncio
import json

from aivanta_graph import CanvasGraph, validate
from aivanta_runtime import get_adapter
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import SessionLocal, get_db
from ..models import CanvasGraphRow, ExecutionRun, GraphVersion, Project, RunEvent
from ..security import Principal, current_principal, require
from ..services import run_service
from ..services.common import scoped_get, tenant_of, validation_policy

router = APIRouter(prefix="/runs", tags=["runs"])


class RunCreate(BaseModel):
    graph_id: str
    project_id: str
    version: int | None = None  # None = simulate the current draft


def run_out(r: ExecutionRun, events: int | None = None) -> dict:
    graph = CanvasGraph.model_validate(r.graph_snapshot)
    return {"id": r.id, "project_id": r.project_id, "graph_id": r.graph_id, "graph_version": r.graph_version, "mode": r.mode, "runtime": r.runtime,
            "status": r.status, "node_status": r.node_status, "tokens": r.tokens, "cost": r.cost, "error": r.error, "trace_id": r.trace_id,
            "idempotency_prefix": r.idempotency_prefix, "started_by": r.started_by, "started_at": r.started_at.isoformat(),
            "ended_at": r.ended_at.isoformat() if r.ended_at else None, "events": events,
            "runtime_ref": {k: v for k, v in ((r.state or {}).get("n8n") or {}).items() if k != "node_map"} or None,
            "nodes": [{"id": n.id, "name": n.name, "type": n.type} for n in graph.nodes]}


@router.post("", status_code=202)
def start_run(body: RunCreate, background: BackgroundTasks, p: Principal = Depends(require("run:start")), db: Session = Depends(get_db)):
    g = scoped_get(db, CanvasGraphRow, body.graph_id, p)
    proj = scoped_get(db, Project, body.project_id, p)
    if body.version is None:
        content, label, mode = g.draft, "draft", "simulation"
        rep = validate(CanvasGraph.model_validate(content), validation_policy(db, tenant_of(db, p)))
        if not rep.ok:
            raise HTTPException(422, {"message": f"Simulation blocked: {len(rep.errors)} validation errors", **rep.summary()})
    else:
        v = db.scalars(select(GraphVersion).where(GraphVersion.graph_id == g.id, GraphVersion.version == body.version)).first()
        if not v:
            raise HTTPException(404, "Version not found")
        content, label, mode = v.content, f"v{v.version}", "published"
    run = ExecutionRun(tenant_id=p.tenant_id, project_id=proj.id, graph_id=g.id, graph_version=label, graph_snapshot=content, mode=mode,
                       runtime=get_adapter().framework, started_by=p.name, status="queued")
    db.add(run)
    db.flush()
    audit.record(db, p.tenant_id, p.name, p.role, "Run started" if mode == "published" else "Simulation started", f"{g.name} {label} · {proj.code} · {run.id}")
    db.commit()
    run_service.dispatch(run.id, "start", background)
    return run_out(run)


@router.get("")
def list_runs(project_id: str | None = None, graph_id: str | None = None, limit: int = 50, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    q = select(ExecutionRun).where(ExecutionRun.tenant_id == p.tenant_id)
    if project_id:
        q = q.where(ExecutionRun.project_id == project_id)
    if graph_id:
        q = q.where(ExecutionRun.graph_id == graph_id)
    return [run_out(r) for r in db.scalars(q.order_by(ExecutionRun.started_at.desc()).limit(min(limit, 200)))]


@router.get("/{run_id}")
def get_run(run_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    r = scoped_get(db, ExecutionRun, run_id, p)
    n = len(db.scalars(select(RunEvent.id).where(RunEvent.run_id == r.id)).all())
    out = run_out(r, n)
    out["outputs"] = r.outputs
    return out


@router.get("/{run_id}/events")
def run_events(run_id: str, after: int = 0, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    r = scoped_get(db, ExecutionRun, run_id, p)
    rows = db.scalars(select(RunEvent).where(RunEvent.run_id == r.id, RunEvent.id > after).order_by(RunEvent.id)).all()
    return [{"id": e.id, "type": e.type, "node_id": e.node_id, "data": e.data, "ts": e.ts.isoformat()} for e in rows]


@router.get("/{run_id}/stream")
async def stream(run_id: str, request: Request, p: Principal = Depends(current_principal)):
    """Server-sent events. EventSource cannot send headers, so the token may be passed as ?access_token=."""
    with SessionLocal() as db:
        scoped_get(db, ExecutionRun, run_id, p)

    async def gen():
        last = 0
        while not await request.is_disconnected():
            with SessionLocal() as db:
                rows = db.scalars(select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.id > last).order_by(RunEvent.id)).all()
                run = db.get(ExecutionRun, run_id)
                for e in rows:
                    last = e.id
                    yield f"id: {e.id}\nevent: {e.type}\ndata: {json.dumps({'type': e.type, 'node_id': e.node_id, 'data': e.data})}\n\n"
                if run.status in ("succeeded", "failed", "cancelled", "awaiting_approval") and not rows:
                    yield f"event: status\ndata: {json.dumps({'status': run.status, 'node_status': run.node_status})}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{run_id}/cancel")
def cancel(run_id: str, p: Principal = Depends(require("run:start")), db: Session = Depends(get_db)):
    r = scoped_get(db, ExecutionRun, run_id, p)
    if r.status in ("succeeded", "failed", "cancelled"):
        raise HTTPException(409, f"Run is already {r.status}")
    r.cancel_requested = True
    if r.status in ("awaiting_approval", "queued"):
        r.status = "cancelled"
    audit.record(db, p.tenant_id, p.name, p.role, "Run cancelled", r.id)
    db.commit()
    return run_out(r)


@router.post("/{run_id}/retry", status_code=202)
def retry(run_id: str, background: BackgroundTasks, p: Principal = Depends(require("run:start")), db: Session = Depends(get_db)):
    r = scoped_get(db, ExecutionRun, run_id, p)
    if r.status != "failed":
        raise HTTPException(409, "Only failed runs can be resumed")
    r.error = None
    audit.record(db, p.tenant_id, p.name, p.role, "Failed run resumed", f"{r.id} · idempotency {r.idempotency_prefix}")
    db.commit()
    run_service.dispatch(r.id, "retry", background)
    return run_out(r)


@router.post("/{run_id}/replay", status_code=202)
def replay(run_id: str, background: BackgroundTasks, p: Principal = Depends(require("run:start")), db: Session = Depends(get_db)):
    r = scoped_get(db, ExecutionRun, run_id, p)
    new = ExecutionRun(tenant_id=r.tenant_id, project_id=r.project_id, graph_id=r.graph_id, graph_version=r.graph_version, graph_snapshot=r.graph_snapshot,
                       mode=r.mode, runtime=r.runtime, started_by=p.name, status="queued")
    db.add(new)
    db.flush()
    audit.record(db, p.tenant_id, p.name, p.role, "Run replayed", f"{r.id} → {new.id}")
    db.commit()
    run_service.dispatch(new.id, "start", background)
    return run_out(new)
