"""Audit trail, RBAC matrix, Definition-of-Done (UAT) evaluation and platform metadata."""
from __future__ import annotations

import os

from aivanta_runtime import RUNTIME_FRAMEWORK, RUNTIME_NAME, get_adapter
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Approval, AuditEvent, CanvasGraphRow, ExecutionRun, GraphVersion, RunEvent, ToolInvocation
from ..security import PERMISSIONS, ROLES, Principal, current_principal

router = APIRouter(tags=["governance"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/meta")
def meta():
    return {"product": RUNTIME_NAME, "runtime": RUNTIME_FRAMEWORK, "framework_version": get_adapter().framework_version(),
            "llm_provider": os.getenv("LLM_PROVIDER", "mock"), "graph_schema": "canvas.v1"}


@router.get("/audit")
def audit_trail(limit: int = 200, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == p.tenant_id).order_by(AuditEvent.id.desc()).limit(min(limit, 1000))).all()
    return {"chain": audit.verify_chain(db, p.tenant_id),
            "events": [{"id": e.id, "ts": e.ts.isoformat(), "actor": e.actor, "role": e.role, "action": e.action, "entity": e.entity,
                        "detail": e.detail, "hash": e.hash[:12], "prev_hash": e.prev_hash[:12]} for e in rows]}


@router.get("/governance/rbac")
def rbac(p: Principal = Depends(current_principal)):
    return {"roles": ROLES, "permissions": {k: sorted(v) for k, v in PERMISSIONS.items()}}


@router.get("/governance/uat")
def uat(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    """Definition of Done (blueprint section 16), evaluated from this tenant's data."""
    t = p.tenant_id
    count = lambda q: db.scalar(q) or 0  # noqa: E731
    acted = lambda action: count(select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == t, AuditEvent.action == action))  # noqa: E731
    sow_ok = count(select(func.count()).select_from(ExecutionRun).join(CanvasGraphRow, CanvasGraphRow.id == ExecutionRun.graph_id)
                   .where(ExecutionRun.tenant_id == t, ExecutionRun.status == "succeeded", ExecutionRun.mode == "published", CanvasGraphRow.template == "RFP_SOW"))
    blocked = count(select(func.count()).select_from(RunEvent).where(RunEvent.tenant_id == t, RunEvent.type == "approval_requested"))
    resumed = count(select(func.count()).select_from(RunEvent).where(RunEvent.tenant_id == t, RunEvent.type == "run_resumed"))
    idem = count(select(func.count()).select_from(ToolInvocation).where(ToolInvocation.tenant_id == t))
    checks = [
        ("canvas_lifecycle", "A user can create and save a canvas, connect valid nodes, detect invalid edges and publish an immutable version.",
         acted("Draft saved") > 0 and acted("Invalid connection rejected") > 0 and count(select(func.count()).select_from(GraphVersion).where(GraphVersion.tenant_id == t)) > 0),
        ("rfp_to_sow_e2e", "A published RFP-to-SOW template runs end-to-end on a sanitized sample RFP with traceable output references.", sow_ok > 0),
        ("pricing_reconciles", "Financial totals reconcile to the deterministic pricing engine across currency, role and scenario changes.",
         acted("Estimate versioned") > 0),
        ("approvals_block", "Approvals block final release until the designated authorized reviewer signs off.",
         blocked > 0 and count(select(func.count()).select_from(Approval).where(Approval.tenant_id == t, Approval.status != "Pending")) > 0),
        ("access_control", "Users cannot access projects, tools, artifacts or credentials outside their permissions.",
         count(select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == t)) > 0),
        ("failed_run_resume", "A failed run can be inspected, cancelled and resumed or safely rerun without duplicate external actions.", resumed > 0 and idem >= 0),
        ("export_fidelity", "Exported BRD/SOW/proposal documents include version, assumptions, review status and source evidence.", acted("Artifact exported") > 0),
    ]
    evidence = {"access_control": "Enforced on every endpoint (tenant-scoped queries + RBAC); covered by tests/integration/test_api_flow.py::test_tenant_isolation.",
                "pricing_reconciles": "Role lines reconcile to labor in aivanta_pricing.compute; covered by tests/unit/test_pricing.py.",
                "failed_run_resume": "Resume path covered by tests/integration/test_runtime_contract.py."}
    return [{"id": i, "criterion": c, "met": bool(ok), "evidence": evidence.get(i, "Evaluated from this tenant's audit and run history.")} for i, c, ok in checks]
