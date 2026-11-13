"""Versioned artifacts and document exports (DOCX / PDF / XLSX)."""
from __future__ import annotations

from aivanta_docs import artifact_to_document, render
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Artifact, Project
from ..security import Principal, current_principal, require
from ..services.common import project_dict, scoped_get

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


class ArtifactEdit(BaseModel):
    content: dict


class ReviewIn(BaseModel):
    decision: str  # approved | changes_requested


def art_out(a: Artifact, with_content: bool = False) -> dict:
    out = {"id": a.id, "project_id": a.project_id, "run_id": a.run_id, "graph_version": a.graph_version, "type": a.type, "version": a.version,
           "source_ids": a.source_ids, "reviewer_role": a.reviewer_role, "approval_state": a.approval_state, "storage_uri": a.storage_uri,
           "created_by": a.created_by, "created_at": a.created_at.isoformat()}
    if with_content:
        out["content"] = a.content
    return out


@router.get("")
def list_artifacts(project_id: str | None = None, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    q = select(Artifact).where(Artifact.tenant_id == p.tenant_id)
    if project_id:
        q = q.where(Artifact.project_id == project_id)
    return [art_out(a) for a in db.scalars(q.order_by(Artifact.type, Artifact.version.desc()))]


@router.get("/{artifact_id}")
def get_artifact(artifact_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return art_out(scoped_get(db, Artifact, artifact_id, p), True)


@router.put("/{artifact_id}", status_code=201)
def edit(artifact_id: str, body: ArtifactEdit, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    """Human edits never overwrite: they create a new version."""
    a = scoped_get(db, Artifact, artifact_id, p)
    latest = db.scalar(select(func.max(Artifact.version)).where(Artifact.project_id == a.project_id, Artifact.type == a.type)) or a.version
    new = Artifact(tenant_id=a.tenant_id, project_id=a.project_id, run_id=a.run_id, graph_version=a.graph_version, type=a.type, version=latest + 1,
                   content=body.content, source_ids=a.source_ids, reviewer_role=a.reviewer_role, approval_state="in_review",
                   storage_uri=a.storage_uri.rsplit("/v", 1)[0] + f"/v{latest + 1}", created_by=p.name)
    db.add(new)
    audit.record(db, p.tenant_id, p.name, p.role, "Artifact edited", f"{a.type} v{latest + 1}")
    db.commit()
    return art_out(new, True)


@router.post("/{artifact_id}/review")
def review(artifact_id: str, body: ReviewIn, p: Principal = Depends(require("artifact:review")), db: Session = Depends(get_db)):
    a = scoped_get(db, Artifact, artifact_id, p)
    if body.decision not in ("approved", "changes_requested"):
        raise HTTPException(422, "decision must be approved or changes_requested")
    a.approval_state = body.decision
    audit.record(db, p.tenant_id, p.name, p.role, f"Artifact {body.decision.replace('_', ' ')}", f"{a.type} v{a.version}")
    db.commit()
    return art_out(a)


@router.get("/{artifact_id}/export")
def export(artifact_id: str, format: str = "docx", p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    a = scoped_get(db, Artifact, artifact_id, p)
    proj = db.get(Project, a.project_id)
    doc = artifact_to_document(art_out(a, True), project_dict(proj))
    try:
        data, mime = render(doc, format)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit.record(db, p.tenant_id, p.name, p.role, "Artifact exported", f"{a.type} v{a.version} · {format}")
    db.commit()
    name = f"{proj.code}_{a.type.replace(' ', '_')}_v{a.version}.{format}"
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})
