"""Canvas graphs: drafts, validation, immutable versions, diff, promotion and export."""
from __future__ import annotations

from aivanta_graph import TEMPLATES, CanvasGraph, diff, edge_problem, template_graph, validate
from aivanta_runtime import get_adapter
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import CanvasGraphRow, ExecutionRun, GraphVersion
from ..security import Principal, current_principal, require
from ..services.common import scoped_get, tenant_of, validation_policy

router = APIRouter(prefix="/graphs", tags=["graphs"])
ENV_ORDER = ["dev", "staging", "prod"]


class GraphCreate(BaseModel):
    name: str
    template: str = "BLANK"


class GraphSave(BaseModel):
    name: str | None = None
    draft: dict


class EdgeCheck(BaseModel):
    source: str
    target: str


def _version_out(v: GraphVersion) -> dict:
    return {"version": v.version, "content_hash": v.content_hash, "environment": v.environment, "published_by": v.published_by,
            "published_at": v.published_at.isoformat()}


def _graph_out(db: Session, g: CanvasGraphRow, report: dict | None = None) -> dict:
    versions = db.scalars(select(GraphVersion).where(GraphVersion.graph_id == g.id).order_by(GraphVersion.version)).all()
    draft = CanvasGraph.model_validate(g.draft)
    latest = versions[-1] if versions else None
    return {"id": g.id, "name": g.name, "template": g.template, "draft": g.draft, "saved_at": g.saved_at.isoformat(), "created_by": g.created_by,
            "versions": [_version_out(v) for v in versions], "draft_hash": draft.content_hash(),
            "unpublished_changes": (latest is None) or latest.content_hash != draft.content_hash(), "validation": report}


@router.get("/templates")
def templates(p: Principal = Depends(current_principal)):
    return [{"key": k, "name": v[0], "description": v[1], "nodes": len(v[2]().nodes), "edges": len(v[2]().edges)} for k, v in TEMPLATES.items()]


@router.get("")
def list_graphs(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    rows = db.scalars(select(CanvasGraphRow).where(CanvasGraphRow.tenant_id == p.tenant_id, CanvasGraphRow.archived.is_(False)).order_by(CanvasGraphRow.saved_at.desc())).all()
    t = tenant_of(db, p)
    pol = validation_policy(db, t)
    out = []
    for g in rows:
        rep = validate(CanvasGraph.model_validate(g.draft), pol)
        item = _graph_out(db, g)
        item.pop("draft")
        item["nodes"] = len(g.draft.get("nodes", []))
        item["edges"] = len(g.draft.get("edges", []))
        item["validation"] = {"errors": len(rep.errors), "warnings": len(rep.warnings)}
        out.append(item)
    return out


@router.post("", status_code=201)
def create_graph(body: GraphCreate, p: Principal = Depends(require("graph:edit")), db: Session = Depends(get_db)):
    if body.template not in TEMPLATES:
        raise HTTPException(422, "Unknown template")
    g = CanvasGraphRow(tenant_id=p.tenant_id, name=body.name, template=body.template, draft=template_graph(body.template).model_dump(), created_by=p.name)
    db.add(g)
    db.flush()
    audit.record(db, p.tenant_id, p.name, p.role, "Canvas created", f"{g.name} from {body.template}")
    db.commit()
    return _graph_out(db, g)


@router.get("/{graph_id}")
def get_graph(graph_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    g = scoped_get(db, CanvasGraphRow, graph_id, p)
    rep = validate(CanvasGraph.model_validate(g.draft), validation_policy(db, tenant_of(db, p)))
    return _graph_out(db, g, rep.summary())


@router.put("/{graph_id}")
def save_draft(graph_id: str, body: GraphSave, p: Principal = Depends(require("graph:edit")), db: Session = Depends(get_db)):
    g = scoped_get(db, CanvasGraphRow, graph_id, p)
    try:
        graph = CanvasGraph.model_validate(body.draft)
    except ValidationError as exc:
        raise HTTPException(422, f"Draft does not match canvas.v1: {exc.errors()[:3]}") from exc
    g.draft = graph.model_dump()
    if body.name:
        g.name = body.name
    from datetime import datetime, timezone
    g.saved_at = datetime.now(timezone.utc)
    audit.record(db, p.tenant_id, p.name, p.role, "Draft saved", f"{g.name} · {graph.content_hash()}")
    db.commit()
    rep = validate(graph, validation_policy(db, tenant_of(db, p)))
    return _graph_out(db, g, rep.summary())


@router.post("/{graph_id}/validate")
def validate_graph(graph_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    g = scoped_get(db, CanvasGraphRow, graph_id, p)
    rep = validate(CanvasGraph.model_validate(g.draft), validation_policy(db, tenant_of(db, p)))
    audit.record(db, p.tenant_id, p.name, p.role, "Graph validated", g.name, {"errors": len(rep.errors), "warnings": len(rep.warnings)})
    db.commit()
    return rep.summary()


@router.post("/{graph_id}/edge-check")
def edge_check(graph_id: str, body: EdgeCheck, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    g = scoped_get(db, CanvasGraphRow, graph_id, p)
    problem = edge_problem(CanvasGraph.model_validate(g.draft), body.source, body.target)
    if problem:
        audit.record(db, p.tenant_id, p.name, p.role, "Invalid connection rejected", f"{g.name}: {body.source} → {body.target}", {"reason": problem})
        db.commit()
    return {"ok": problem is None, "problem": problem}


@router.post("/{graph_id}/publish", status_code=201)
def publish(graph_id: str, p: Principal = Depends(require("graph:publish")), db: Session = Depends(get_db)):
    g = scoped_get(db, CanvasGraphRow, graph_id, p)
    graph = CanvasGraph.model_validate(g.draft)
    rep = validate(graph, validation_policy(db, tenant_of(db, p)))
    if not rep.ok:
        raise HTTPException(422, {"message": f"Publish blocked: {len(rep.errors)} validation errors", **rep.summary()})
    latest = db.scalars(select(GraphVersion).where(GraphVersion.graph_id == g.id).order_by(GraphVersion.version.desc())).first()
    if latest and latest.content_hash == graph.content_hash():
        raise HTTPException(409, f"No changes since v{latest.version}; nothing to publish")
    v = GraphVersion(tenant_id=p.tenant_id, graph_id=g.id, version=(latest.version + 1) if latest else 1, content=graph.model_dump(),
                     content_hash=graph.content_hash(), environment="dev", published_by=p.name)
    db.add(v)
    audit.record(db, p.tenant_id, p.name, p.role, "Graph version published", f"{g.name} v{v.version} · {v.content_hash}")
    db.commit()
    return _version_out(v) | {"compiled_for": get_adapter().framework}


@router.get("/{graph_id}/versions/{version}")
def get_version(graph_id: str, version: int, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    g = scoped_get(db, CanvasGraphRow, graph_id, p)
    v = db.scalars(select(GraphVersion).where(GraphVersion.graph_id == g.id, GraphVersion.version == version)).first()
    if not v:
        raise HTTPException(404, "Version not found")
    return _version_out(v) | {"content": v.content}


@router.get("/{graph_id}/diff")
def diff_versions(graph_id: str, against: int, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    g = scoped_get(db, CanvasGraphRow, graph_id, p)
    v = db.scalars(select(GraphVersion).where(GraphVersion.graph_id == g.id, GraphVersion.version == against)).first()
    if not v:
        raise HTTPException(404, "Version not found")
    return {"against": against, "against_hash": v.content_hash, **diff(CanvasGraph.model_validate(v.content), CanvasGraph.model_validate(g.draft))}


@router.post("/{graph_id}/versions/{version}/promote")
def promote(graph_id: str, version: int, p: Principal = Depends(require("graph:promote")), db: Session = Depends(get_db)):
    g = scoped_get(db, CanvasGraphRow, graph_id, p)
    v = db.scalars(select(GraphVersion).where(GraphVersion.graph_id == g.id, GraphVersion.version == version)).first()
    if not v:
        raise HTTPException(404, "Version not found")
    if v.environment == "prod":
        raise HTTPException(409, "Already in prod")
    target = ENV_ORDER[ENV_ORDER.index(v.environment) + 1]
    if target == "prod":
        rep = validate(CanvasGraph.model_validate(v.content), validation_policy(db, tenant_of(db, p)))
        if not rep.ok:
            raise HTTPException(422, f"Promotion blocked: v{version} has {len(rep.errors)} validation errors under current policy")
        ok_runs = db.scalar(select(func.count()).select_from(ExecutionRun).where(ExecutionRun.graph_id == g.id, ExecutionRun.graph_version == f"v{version}",
                                                                                 ExecutionRun.status == "succeeded"))
        if not ok_runs:
            raise HTTPException(422, f"Promotion blocked: v{version} has no succeeded run yet")
    v.environment = target
    audit.record(db, p.tenant_id, p.name, p.role, "Version promoted", f"{g.name} v{version} → {target}")
    db.commit()
    return _version_out(v)


@router.get("/{graph_id}/export")
def export(graph_id: str, version: int | None = None, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    g = scoped_get(db, CanvasGraphRow, graph_id, p)
    content = g.draft
    if version:
        v = db.scalars(select(GraphVersion).where(GraphVersion.graph_id == g.id, GraphVersion.version == version)).first()
        if not v:
            raise HTTPException(404, "Version not found")
        content = v.content
    return get_adapter().export(CanvasGraph.model_validate(content)) | {"graph": g.name, "version": version or "draft"}


@router.delete("/{graph_id}", status_code=204)
def archive(graph_id: str, p: Principal = Depends(require("graph:edit")), db: Session = Depends(get_db)):
    g = scoped_get(db, CanvasGraphRow, graph_id, p)
    g.archived = True
    audit.record(db, p.tenant_id, p.name, p.role, "Canvas archived", g.name)
    db.commit()
