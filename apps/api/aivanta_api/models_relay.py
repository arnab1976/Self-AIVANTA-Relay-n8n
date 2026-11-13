"""Commercial SaaS entities: subscriptions (plan, status, cloud, n8n placement) and access requests."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

PLANS = {
    "Starter": {"price": "₹1.5L / month", "max_users": 15, "isolation": "row-level-security", "n8n": "shared",
                "features": ["Shared database (RLS)", "Shared n8n (queue mode)", "Community support"]},
    "Growth": {"price": "₹4L / month", "max_users": 75, "isolation": "schema-per-tenant", "n8n": "shared",
               "features": ["Schema per tenant", "SSO (OIDC)", "Business-hours support"]},
    "Enterprise": {"price": "Custom", "max_users": 100000, "isolation": "dedicated-database", "n8n": "dedicated",
                   "features": ["Dedicated database", "Dedicated n8n instance", "24×7 support · 99.9% SLA"]},
}


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Subscription(Base):
    __tablename__ = "subscriptions"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    plan: Mapped[str] = mapped_column(String(32), default="Growth")
    status: Mapped[str] = mapped_column(String(16), default="Active")          # Active | Suspended
    cloud: Mapped[str] = mapped_column(String(16), default="AWS")              # AWS | Azure | GCP
    n8n_placement: Mapped[str] = mapped_column(String(16), default="shared")   # shared | dedicated
    admin_email: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AccessRequest(Base):
    __tablename__ = "access_requests"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    kind: Mapped[str] = mapped_column(String(16))                              # join | new_org
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200))
    organisation: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32), default="presales")
    details: Mapped[dict] = mapped_column(JSON, default=dict)                   # plan, cloud, region, currency for new_org
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="Pending")         # Pending | Approved | Rejected
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
