from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Project, Tenant
from ..security import Principal, current_principal, require
from ..services.common import snapshot_age, tenant_of
from ..services.seed import DEFAULT_ESTIMATE, DEFAULT_WORKLOAD, add_graph, create_tenant

router = APIRouter(prefix="/tenants", tags=["tenants"])
MODEL_PROFILES = ["enterprise-reasoning", "enterprise-fast", "local-open-weight", "experimental-preview"]


def tenant_out(t: Tenant) -> dict:
    return {"id": t.id, "code": t.code, "name": t.name, "currency": t.currency, "region": t.region, "isolation_model": t.isolation_model,
            "identity_provider": t.identity_provider, "margin_floor_pct": t.margin_floor_pct, "discount_limit_pct": t.discount_limit_pct,
            "allowed_models": t.allowed_models, "model_profiles": MODEL_PROFILES, "rate_card": t.rate_card, "rate_card_version": t.rate_card_version,
            "fx_rate": t.fx_rate, "fx_version": t.fx_version, "price_snapshot_date": t.price_snapshot_date,
            "price_snapshot_age_days": snapshot_age(t), "integrations": t.integrations}


class TenantPatch(BaseModel):
    allowed_models: list[str] | None = None
    margin_floor_pct: float | None = None
    discount_limit_pct: float | None = None
    integrations: dict | None = None
    refresh_price_snapshot: bool = False


class RateCardPatch(BaseModel):
    rates: dict[str, float] | None = None
    fx_rate: float | None = None


class TenantCreate(BaseModel):
    code: str
    name: str
    currency: str = "INR"
    region: str = "India (Mumbai)"
    isolation_model: str = "schema-per-tenant"


@router.get("/current")
def current(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    return tenant_out(tenant_of(db, p))


@router.patch("/current")
def patch_current(body: TenantPatch, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    t = tenant_of(db, p)
    if body.refresh_price_snapshot and (p.can("pricing:edit") or p.can("tenant:admin")):
        t.price_snapshot_date = date.today().isoformat()
        audit.record(db, t.id, p.name, p.role, "Price snapshot refreshed", t.price_snapshot_date)
    admin_fields = body.model_dump(exclude_none=True, exclude={"refresh_price_snapshot"})
    if admin_fields:
        if not p.can("tenant:admin"):
            raise HTTPException(403, "Only the Platform Administrator can change tenant policy")
        if body.allowed_models is not None:
            unknown = set(body.allowed_models) - set(MODEL_PROFILES)
            if unknown:
                raise HTTPException(422, f"Unknown model profiles: {sorted(unknown)}")
        for k, v in admin_fields.items():
            setattr(t, k, v)
        audit.record(db, t.id, p.name, p.role, "Tenant policy updated", t.name, admin_fields)
    db.commit()
    return tenant_out(t)


@router.patch("/current/rate-card")
def patch_rate_card(body: RateCardPatch, p: Principal = Depends(require("pricing:edit")), db: Session = Depends(get_db)):
    t = tenant_of(db, p)
    if body.rates:
        if any(v < 0 for v in body.rates.values()):
            raise HTTPException(422, "Rates cannot be negative")
        t.rate_card = {**t.rate_card, **body.rates}
        n = int(t.rate_card_version.rsplit("v", 1)[-1]) + 1 if t.rate_card_version.rsplit("v", 1)[-1].isdigit() else 2
        t.rate_card_version = f"{t.rate_card_version.rsplit('v', 1)[0]}v{n}"
        audit.record(db, t.id, p.name, p.role, "Rate card versioned", t.rate_card_version, body.rates)
    if body.fx_rate:
        t.fx_rate = body.fx_rate
        t.fx_version = f"FX-{date.today().isoformat()}"
        audit.record(db, t.id, p.name, p.role, "Currency rate versioned", t.fx_version, {"fx_rate": body.fx_rate})
    db.commit()
    return tenant_out(t)


@router.get("")
def list_tenants(p: Principal = Depends(require("tenant:admin")), db: Session = Depends(get_db)):
    return [{"id": t.id, "code": t.code, "name": t.name, "region": t.region, "currency": t.currency, "isolation_model": t.isolation_model,
             "identity_provider": t.identity_provider} for t in db.scalars(select(Tenant).order_by(Tenant.created_at))]


@router.post("", status_code=201)
def provision(body: TenantCreate, p: Principal = Depends(require("tenant:admin")), db: Session = Depends(get_db)):
    if db.scalars(select(Tenant).where(Tenant.code == body.code.upper())).first():
        raise HTTPException(409, "Tenant code already exists")
    t = create_tenant(db, body.code.upper()[:8], body.name, body.currency, body.region, body.isolation_model)
    db.add(Project(tenant_id=t.id, code=f"{t.code}-0001", client="Sample Client Co.", name="Pilot proposal", scope="Pilot engagement used to validate the RFP-to-SOW canvas.",
                   region=t.region, currency=t.currency, owner=p.name, estimate_inputs=DEFAULT_ESTIMATE, workload={**DEFAULT_WORKLOAD, "region": t.region},
                   clarifications=[{"question": "Confirm integration scope for phase 1", "open": True}]))
    add_graph(db, t, "RFP_SOW", "RFP-to-SOW", ["dev"], by=p.name)
    audit.record(db, p.tenant_id, p.name, p.role, "Tenant provisioned", f"{t.name} · {t.isolation_model}")
    db.commit()
    return tenant_out(t)
