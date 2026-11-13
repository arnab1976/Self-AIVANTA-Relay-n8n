from __future__ import annotations

import hashlib
import os
from pathlib import Path

from aivanta_connectors import UploadRejected, chunk, embed, ingest
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..models import Approval, Artifact, Document, DocumentChunk, Estimate, ExecutionRun, Project, RunEvent
from ..security import Principal, current_principal, require
from ..services.common import project_dict, scoped_get, tenant_of
from ..services.seed import DEFAULT_ESTIMATE, DEFAULT_WORKLOAD

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectIn(BaseModel):
    client: str
    name: str
    industry: str = "BFSI"
    deal_stage: str = "RFP received"
    delivery_model: str = "Fixed price"
    region: str | None = None
    scope: str = ""
    deadline: str | None = None
    classification: str = "Confidential"


class ProjectPatch(BaseModel):
    deal_stage: str | None = None
    scope: str | None = None
    deadline: str | None = None
    clarifications: list[dict] | None = None
    estimate_inputs: dict | None = None
    workload: dict | None = None


@router.get("")
def list_projects(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    rows = db.scalars(select(Project).where(Project.tenant_id == p.tenant_id).order_by(Project.created_at.desc())).all()
    docs = dict(db.execute(select(Document.project_id, func.count()).where(Document.tenant_id == p.tenant_id).group_by(Document.project_id)).all())
    return [project_dict(r) | {"documents": docs.get(r.id, 0), "open_clarifications": sum(1 for c in r.clarifications or [] if c.get("open"))} for r in rows]


@router.post("", status_code=201)
def create_project(body: ProjectIn, p: Principal = Depends(require("project:write")), db: Session = Depends(get_db)):
    t = tenant_of(db, p)
    n = db.scalar(select(func.count()).select_from(Project).where(Project.tenant_id == t.id)) or 0
    proj = Project(tenant_id=t.id, code=f"{t.code}-{1050 + n}", currency=t.currency, owner=p.name, region=body.region or t.region,
                   estimate_inputs=DEFAULT_ESTIMATE, workload={**DEFAULT_WORKLOAD, "region": body.region or t.region},
                   clarifications=[], **body.model_dump(exclude={"region"}))
    db.add(proj)
    db.flush()
    audit.record(db, t.id, p.name, p.role, "Project created", f"{proj.code} · {proj.client}")
    db.commit()
    return project_dict(proj)


@router.get("/{project_id}")
def get_project(project_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    proj = scoped_get(db, Project, project_id, p)
    docs = db.scalars(select(Document).where(Document.project_id == proj.id).order_by(Document.created_at.desc())).all()
    return project_dict(proj) | {"documents": [{"id": d.id, "filename": d.filename, "pages": d.pages, "pii_redactions": d.pii_redactions,
                                                "scan_engine": d.scan_engine, "sha256": d.sha256, "created_at": d.created_at.isoformat()} for d in docs]}


@router.patch("/{project_id}")
def patch_project(project_id: str, body: ProjectPatch, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    proj = scoped_get(db, Project, project_id, p)
    changes = body.model_dump(exclude_none=True)
    if "estimate_inputs" in changes and not p.can("estimate:write"):
        raise HTTPException(403, "Estimate inputs can be changed by Finance, Presales or PMO")
    if set(changes) - {"estimate_inputs", "workload"} and not p.can("project:write"):
        raise HTTPException(403, "Project changes require Presales, Solution Architect or PMO")
    for k, v in changes.items():
        setattr(proj, k, v)
    audit.record(db, p.tenant_id, p.name, p.role, "Project updated", proj.code, {"fields": sorted(changes)})
    db.commit()
    return project_dict(proj)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, p: Principal = Depends(require("project:write")), db: Session = Depends(get_db)):
    """Remove a project and its intake / run / commercial rows for this tenant."""
    proj = scoped_get(db, Project, project_id, p)
    code = proj.code
    run_ids = list(db.scalars(select(ExecutionRun.id).where(ExecutionRun.project_id == proj.id, ExecutionRun.tenant_id == p.tenant_id)))
    if run_ids:
        db.query(RunEvent).filter(RunEvent.run_id.in_(run_ids)).delete(synchronize_session=False)
        db.query(Approval).filter(Approval.run_id.in_(run_ids)).delete(synchronize_session=False)
    db.query(Approval).filter(Approval.project_id == proj.id, Approval.tenant_id == p.tenant_id).delete(synchronize_session=False)
    db.query(ExecutionRun).filter(ExecutionRun.project_id == proj.id, ExecutionRun.tenant_id == p.tenant_id).delete(synchronize_session=False)
    db.query(Artifact).filter(Artifact.project_id == proj.id, Artifact.tenant_id == p.tenant_id).delete(synchronize_session=False)
    db.query(Estimate).filter(Estimate.project_id == proj.id, Estimate.tenant_id == p.tenant_id).delete(synchronize_session=False)
    db.query(DocumentChunk).filter(DocumentChunk.project_id == proj.id, DocumentChunk.tenant_id == p.tenant_id).delete(synchronize_session=False)
    docs = db.scalars(select(Document).where(Document.project_id == proj.id, Document.tenant_id == p.tenant_id)).all()
    for doc in docs:
        try:
            Path(doc.storage_uri).unlink(missing_ok=True)
        except OSError:
            pass
        db.delete(doc)
    folder = Path(get_settings().storage_dir) / p.tenant_id / proj.id
    if folder.exists():
        for child in folder.glob("*"):
            try:
                child.unlink()
            except OSError:
                pass
        try:
            folder.rmdir()
        except OSError:
            pass
    db.delete(proj)
    audit.record(db, p.tenant_id, p.name, p.role, "Project deleted", code)
    db.commit()


@router.post("/{project_id}/rfp", status_code=201)
async def upload_rfp(project_id: str, file: UploadFile = File(...), p: Principal = Depends(require("project:write")), db: Session = Depends(get_db)):
    proj = scoped_get(db, Project, project_id, p)
    data = await file.read()
    try:
        res = ingest(data, file.filename or "upload.bin")
    except UploadRejected as exc:
        audit.record(db, p.tenant_id, p.name, p.role, "Upload rejected", f"{proj.code} · {file.filename}", {"reason": str(exc)})
        db.commit()
        raise HTTPException(422, str(exc)) from exc
    sha = hashlib.sha256(data).hexdigest()
    folder = Path(get_settings().storage_dir) / p.tenant_id / proj.id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sha[:16]}{os.path.splitext(file.filename or '')[1].lower()}"
    path.write_bytes(data)  # at-rest encryption is provided by the storage layer (encrypted volume / bucket KMS)
    doc = Document(tenant_id=p.tenant_id, project_id=proj.id, filename=file.filename or path.name, storage_uri=str(path), sha256=sha,
                   pages=res.pages, pii_redactions=res.pii_counts, scan_engine=res.scan.engine, text=res.text)
    db.add(doc)
    db.flush()
    parts = chunk(res.text)
    for i, (txt, vec) in enumerate(zip(parts, embed(parts) if parts else [])):
        db.add(DocumentChunk(tenant_id=p.tenant_id, project_id=proj.id, document_id=doc.id, ordinal=i, text=txt, embedding=vec))
    audit.record(db, p.tenant_id, p.name, p.role, "RFP ingested", f"{proj.code} · {doc.filename}",
                 {"scan": res.scan.engine, "pii_redactions": res.pii_counts, "chunks": len(parts)})
    db.commit()
    return {"id": doc.id, "filename": doc.filename, "pages": doc.pages, "pii_redactions": res.pii_counts, "scan_engine": res.scan.engine,
            "chunks": len(parts), "characters": len(res.text)}
