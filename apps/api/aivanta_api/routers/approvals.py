"""Human approvals: role-gated decisions with segregation of duties."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Approval, ExecutionRun
from ..security import ROLES, Principal, current_principal
from ..services import run_service
from ..services.common import scoped_get

router = APIRouter(prefix="/approvals", tags=["approvals"])
SEGREGATED_ROLES = {"finance", "reviewer"}  # requester may not approve their own commercial / final sign-off


class ApprovalCreate(BaseModel):
    kind: str
    approver_role: str
    evidence: str = ""
    project_id: str | None = None


class DecisionIn(BaseModel):
    decision: str  # Approved | Rejected
    comment: str = ""


def approval_out(a: Approval) -> dict:
    return {"id": a.id, "run_id": a.run_id, "node_id": a.node_id, "project_id": a.project_id, "kind": a.kind, "approver_role": a.approver_role,
            "approver_label": ROLES.get(a.approver_role, a.approver_role), "evidence": a.evidence, "status": a.status, "requested_by": a.requested_by,
            "requested_at": a.requested_at.isoformat(), "sla_hours": a.sla_hours, "decided_by": a.decided_by,
            "decided_at": a.decided_at.isoformat() if a.decided_at else None, "comment": a.comment}


@router.get("")
def list_approvals(status: str | None = None, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    q = select(Approval).where(Approval.tenant_id == p.tenant_id)
    if status:
        q = q.where(Approval.status == status)
    return [approval_out(a) for a in db.scalars(q.order_by(Approval.requested_at.desc()).limit(200))]


@router.post("", status_code=201)
def request_approval(body: ApprovalCreate, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    if body.approver_role not in ROLES:
        raise HTTPException(422, "Unknown approver role")
    a = Approval(tenant_id=p.tenant_id, kind=body.kind, approver_role=body.approver_role, evidence=body.evidence, project_id=body.project_id, requested_by=p.name)
    db.add(a)
    audit.record(db, p.tenant_id, p.name, p.role, "Approval requested", body.kind)
    db.commit()
    return approval_out(a)


@router.post("/{approval_id}/decide")
def decide(approval_id: str, body: DecisionIn, background: BackgroundTasks, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    a = scoped_get(db, Approval, approval_id, p)
    if body.decision not in ("Approved", "Rejected"):
        raise HTTPException(422, "decision must be Approved or Rejected")
    if a.status != "Pending":
        raise HTTPException(409, f"Already {a.status.lower()}")
    if a.approver_role not in p.roles:
        raise HTTPException(403, f"Only {ROLES.get(a.approver_role)} can decide this approval")
    if a.approver_role in SEGREGATED_ROLES and a.requested_by == p.name:
        raise HTTPException(403, "Segregation of duties: you requested this approval, so another approver must decide it")
    a.status, a.decided_by, a.decided_at, a.comment = body.decision, p.name, datetime.now(timezone.utc), body.comment
    audit.record(db, p.tenant_id, p.name, p.role, f"{a.kind} {body.decision.lower()}", a.run_id or a.project_id or a.id, {"comment": body.comment})
    db.commit()
    if a.run_id:
        run = db.get(ExecutionRun, a.run_id)
        if run and run.status in ("awaiting_approval", "running", "queued"):
            run_service.dispatch(run.id, "resume", background)
    return approval_out(a)
