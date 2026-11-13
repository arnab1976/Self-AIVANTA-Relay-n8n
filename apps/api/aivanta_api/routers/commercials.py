"""Estimation, deterministic pricing and cloud FinOps."""
from __future__ import annotations

from aivanta_pricing import blueprint_example
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Approval, Estimate, Project
from ..security import Principal, current_principal, require
from ..services.common import cloud_compare, cloud_monthly, price, scoped_get, tenant_of

router = APIRouter(tags=["commercials"])


class PricingRequest(BaseModel):
    inputs: dict


class EstimateRequest(BaseModel):
    inputs: dict | None = None


class WorkloadRequest(BaseModel):
    workload: dict


@router.post("/pricing/calculate")
def calculate(body: PricingRequest, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return price(tenant_of(db, p), body.inputs)


@router.get("/pricing/blueprint-example")
def example(p: Principal = Depends(current_principal)):
    return blueprint_example().to_dict()


def _project_inputs(db, tenant, proj: Project, override: dict | None) -> dict:
    est = {**(proj.estimate_inputs or {}), **(override or {})}
    provider = est.get("provider", "azure")
    return {**est, "cloud_monthly": str(cloud_monthly(tenant, proj.workload or {}, provider)) if proj.workload else "0"}


@router.post("/projects/{project_id}/estimates/preview")
def preview(project_id: str, body: EstimateRequest, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    proj = scoped_get(db, Project, project_id, p)
    t = tenant_of(db, p)
    inputs = _project_inputs(db, t, proj, body.inputs)
    return price(t, inputs) | {"inputs": inputs}


@router.post("/projects/{project_id}/estimates", status_code=201)
def save_estimate(project_id: str, body: EstimateRequest, p: Principal = Depends(require("estimate:write")), db: Session = Depends(get_db)):
    proj = scoped_get(db, Project, project_id, p)
    t = tenant_of(db, p)
    if body.inputs:
        proj.estimate_inputs = {**(proj.estimate_inputs or {}), **body.inputs}
    inputs = _project_inputs(db, t, proj, None)
    res = price(t, inputs)
    n = (db.scalar(select(func.max(Estimate.version)).where(Estimate.project_id == proj.id)) or 0) + 1
    e = Estimate(tenant_id=t.id, project_id=proj.id, version=n, inputs=inputs, result=res["result"], scenarios=res["scenarios"], flags=res["flags"],
                 currency=t.currency, selling_price=res["result"]["selling_price"], margin_pct=res["result"]["effective_margin_pct"], created_by=p.name)
    db.add(e)
    if any(f["code"] == "discount_exception" for f in res["flags"]):
        db.add(Approval(tenant_id=t.id, project_id=proj.id, kind="Discount exception", approver_role="finance",
                        evidence=f"{proj.code} estimate v{n}: discount {inputs.get('discount_pct')}%", requested_by=p.name))
    audit.record(db, t.id, p.name, p.role, "Estimate versioned", f"{proj.code} v{n} · {res['result']['selling_price']} {t.currency}",
                 {"flags": [f["code"] for f in res["flags"]]})
    db.commit()
    return {"version": n, **res, "inputs": inputs}


@router.get("/projects/{project_id}/estimates")
def list_estimates(project_id: str, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    proj = scoped_get(db, Project, project_id, p)
    rows = db.scalars(select(Estimate).where(Estimate.project_id == proj.id).order_by(Estimate.version.desc())).all()
    return [{"version": e.version, "selling_price": e.selling_price, "margin_pct": e.margin_pct, "currency": e.currency, "flags": e.flags,
             "created_by": e.created_by, "created_at": e.created_at.isoformat()} for e in rows]


@router.post("/finops/compare")
def compare(body: WorkloadRequest, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return cloud_compare(tenant_of(db, p), body.workload)
