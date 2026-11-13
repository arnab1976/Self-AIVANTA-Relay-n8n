"""Demo data for the SaaS layer: subscriptions for the seeded tenants and two sample access requests."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Tenant
from ..models_relay import AccessRequest, Subscription

SUBS = {"FP": ("Enterprise", "AWS", "shared"), "US": ("Enterprise", "Azure", "dedicated"), "HX": ("Starter", "GCP", "shared")}


def seed_relay(db: Session) -> None:
    if db.scalars(select(Subscription)).first():
        return
    tenants = {t.code: t for t in db.scalars(select(Tenant))}
    for code, (plan, cloud, n8n) in SUBS.items():
        if code in tenants:
            db.add(Subscription(tenant_id=tenants[code].id, plan=plan, cloud=cloud, n8n_placement=n8n, status="Active",
                                admin_email=f"admin@{code.lower()}.example"))
    db.add(AccessRequest(kind="new_org", name="Priya Menon", email="priya.menon@northwind.example", organisation="Northwind Analytics",
                         role="admin", details={"plan": "Growth", "cloud": "AWS", "region": "India (Mumbai)", "currency": "INR"},
                         note="Pilot for 20 presales users"))
    if "FP" in tenants:
        db.add(AccessRequest(kind="join", tenant_id=tenants["FP"].id, name="Vikram Menon", email="vikram.menon@fp.example",
                             organisation="Feuji Software", role="presales", note="New joiner, BFSI pod"))
    db.commit()
