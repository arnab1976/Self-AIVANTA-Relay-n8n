"""Tenant scoping, serialization and shared domain helpers."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TypeVar

from aivanta_connectors import load_registry
from aivanta_graph import ToolPolicy as GraphToolPolicy
from aivanta_graph import ValidationPolicy
from aivanta_pricing import PricingInput, PricingPolicy, check, compute, scenarios
from aivanta_pricing import cloud as cloud_svc
from aivanta_templates import load_templates
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project, Tenant, ToolPolicy
from ..security import Principal

M = TypeVar("M")


def scoped_get(db: Session, model: type[M], obj_id: str, p: Principal) -> M:
    """Fetch by id within the caller's tenant. Other tenants' rows are indistinguishable from missing rows."""
    obj = db.get(model, obj_id)
    if obj is None or getattr(obj, "tenant_id", None) != p.tenant_id:
        raise HTTPException(404, f"{model.__name__} not found")
    return obj


def tenant_of(db: Session, p: Principal) -> Tenant:
    t = db.get(Tenant, p.tenant_id)
    if not t:
        # Match /auth/me: a token whose tenant row is gone must re-authenticate (not a generic 404).
        raise HTTPException(401, "Tenant no longer exists; sign in again")
    return t


def approved_tools(db: Session, tenant_id: str) -> dict[str, bool]:
    reg = load_registry()
    out = {k: v.approved for k, v in reg.items()}
    for row in db.scalars(select(ToolPolicy).where(ToolPolicy.tenant_id == tenant_id)):
        out[row.tool_id] = row.approved
    return out


def validation_policy(db: Session, tenant: Tenant) -> ValidationPolicy:
    reg = load_registry()
    appr = approved_tools(db, tenant.id)
    return ValidationPolicy(allowed_models=set(tenant.allowed_models or []),
                            tools={k: GraphToolPolicy(approved=appr.get(k, False), external=v.external) for k, v in reg.items()},
                            known_templates=set(load_templates().keys()))


def project_dict(p: Project) -> dict:
    return {c.name: getattr(p, c.name) for c in Project.__table__.columns if c.name not in ("created_at",)} | \
        {"created_at": p.created_at.isoformat() if p.created_at else None}


def snapshot_age(tenant: Tenant) -> int:
    return (date.today() - date.fromisoformat(tenant.price_snapshot_date)).days


def cloud_compare(tenant: Tenant, workload: dict) -> dict:
    fx = Decimal(str(tenant.fx_rate)) if tenant.currency != "USD" else Decimal(1)
    res = cloud_svc.compare(workload, fx_rate=fx, currency=tenant.currency)
    res["tenant_snapshot_date"] = tenant.price_snapshot_date
    res["tenant_snapshot_age_days"] = snapshot_age(tenant)
    return res


def price(tenant: Tenant, inputs: dict) -> dict:
    """Run the deterministic pricing engine with the tenant's versioned rate card and policy."""
    data = dict(inputs)
    data.setdefault("currency", tenant.currency)
    data["rate_card_version"] = tenant.rate_card_version
    data["fx_version"] = tenant.fx_version
    try:
        inp = PricingInput.from_dict(data, tenant.rate_card)
        result = compute(inp)
    except (ValueError, ArithmeticError) as exc:
        raise HTTPException(422, str(exc)) from exc
    policy = PricingPolicy(margin_floor_pct=Decimal(str(tenant.margin_floor_pct)), discount_limit_pct=Decimal(str(tenant.discount_limit_pct)),
                           price_snapshot_age_days=snapshot_age(tenant))
    return {"result": result.to_dict(), "scenarios": {k: v.to_dict() for k, v in scenarios(inp).items()},
            "flags": check(inp, result, policy)}


def cloud_monthly(tenant: Tenant, workload: dict, provider: str) -> Decimal:
    res = cloud_compare(tenant, workload)
    return Decimal(res["providers"].get(provider, next(iter(res["providers"].values())))["base"]["monthly"])
