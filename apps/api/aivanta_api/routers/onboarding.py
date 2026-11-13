"""Multi-tenant SaaS onboarding: Request Access, Tenant Admin approvals and the Provider Admin console.

* **Request Access** (public): ask to join an existing tenant, or ask for a new organisation tenant.
* **Tenant Admin** (role ``admin`` inside a tenant): approves join requests → user created with the requested role.
* **Provider Admin** (the SaaS operator): approves new organisations → tenant provisioned with plan, cloud,
  region, isolation model and n8n placement; changes plans; suspends and reactivates tenants; sees usage.

Provider identities are separate from tenant identities. In ``AUTH_MODE=dev`` use
``POST /api/provider/dev-login``; with OIDC, users whose roles/groups contain
``PROVIDER_ROLE`` (default ``aivanta-provider``) are provider admins.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone

import jwt
from aivanta_runtime import get_adapter
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import SessionLocal, get_db
from ..models import ExecutionRun, Project, Tenant, User
from ..models_relay import PLANS, AccessRequest, Subscription
from ..security import ROLES, Principal, decode_token, require
from ..services.seed import DEFAULT_ESTIMATE, DEFAULT_WORKLOAD, add_graph, create_tenant

router = APIRouter(tags=["onboarding & provider"])
PROVIDER_TID = "__provider__"
CLOUDS = ["AWS", "Azure", "GCP"]
REGIONS = ["India (Mumbai)", "India (Hyderabad)", "US East", "EU (Frankfurt)", "Singapore"]


def _now():
    return datetime.now(timezone.utc)


def subscription(db: Session, tenant: Tenant) -> Subscription:
    sub = db.get(Subscription, tenant.id)
    if sub is None:
        sub = Subscription(tenant_id=tenant.id, plan="Enterprise", status="Active", cloud="AWS", n8n_placement="shared")
        db.add(sub)
        db.flush()
    return sub


# ---------------------------------------------------------------------------
# suspension guard (used as middleware by main.py)
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, bool]] = {}


def tenant_suspended(tenant_id: str) -> bool:
    hit = _cache.get(tenant_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    with SessionLocal() as db:
        sub = db.get(Subscription, tenant_id)
        val = bool(sub and sub.status == "Suspended")
    _cache[tenant_id] = (time.monotonic() + 10, val)
    return val


def suspended_from_request(request: Request) -> bool:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return False
    try:
        claims = decode_token(auth[7:])
    except jwt.PyJWTError:
        return False
    tid = claims.get("tid") or claims.get(get_settings().oidc_tenant_claim)
    return bool(tid and tid != PROVIDER_TID and tenant_suspended(tid))


# ---------------------------------------------------------------------------
# provider identity
# ---------------------------------------------------------------------------
class ProviderLogin(BaseModel):
    name: str = "Platform Operations"
    read_only: bool = False


def provider(request: Request) -> Principal:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Provider sign-in required")
    try:
        claims = decode_token(auth[7:])
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"Invalid token: {exc}") from exc
    s = get_settings()
    if s.auth_mode == "dev":
        if claims.get("tid") != PROVIDER_TID:
            raise HTTPException(403, "Provider Admin only")
        return Principal(claims["sub"], PROVIDER_TID, claims.get("email", ""), claims.get("name", ""), list(claims.get("roles", [])))
    marker = os.getenv("PROVIDER_ROLE", "aivanta-provider")
    if marker not in list(claims.get(s.oidc_roles_claim, [])) + list(claims.get("groups", [])):
        raise HTTPException(403, "Provider Admin only")
    return Principal(claims.get("oid") or claims["sub"], PROVIDER_TID, claims.get("preferred_username", ""), claims.get("name", ""), ["provider"])


def provider_write(p: Principal = Depends(provider)) -> Principal:
    if "provider" not in p.roles:
        raise HTTPException(403, "Provider support accounts are read-only")
    return p


@router.post("/provider/dev-login")
def provider_dev_login(body: ProviderLogin):
    s = get_settings()
    if s.auth_mode != "dev":
        raise HTTPException(404, "Dev login is disabled; sign in with the provider identity provider.")
    now = _now()
    role = "provider_support" if body.read_only else "provider"
    token = jwt.encode({"sub": f"prov-{re.sub(r'[^a-z0-9]', '', body.name.lower())[:20]}", "tid": PROVIDER_TID, "name": body.name,
                        "email": f"{body.name.lower().replace(' ', '.')}@provider.example", "roles": [role], "iat": now,
                        "exp": now + timedelta(minutes=s.jwt_ttl_minutes), "iss": "aivanta-dev"}, s.jwt_secret, algorithm="HS256")
    return {"token": token, "provider": {"name": body.name, "role": role}}


# ---------------------------------------------------------------------------
# public
# ---------------------------------------------------------------------------
@router.get("/public/plans")
def plans():
    return {"plans": PLANS, "clouds": CLOUDS, "regions": REGIONS}


@router.get("/public/tenants")
def directory(db: Session = Depends(get_db)):
    """Tenants a person may ask to join. Set PUBLIC_TENANT_DIRECTORY=false to require the tenant code instead."""
    if os.getenv("PUBLIC_TENANT_DIRECTORY", "true").lower() != "true":
        return []
    rows = db.scalars(select(Tenant).order_by(Tenant.name)).all()
    return [{"code": t.code, "name": t.name} for t in rows if subscription(db, t).status == "Active"]


class AccessRequestIn(BaseModel):
    kind: str = Field(pattern="^(join|new_org)$")
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    organisation: str = Field(min_length=2, max_length=200)
    tenant_code: str | None = None
    role: str = "presales"
    plan: str = "Growth"
    cloud: str = "AWS"
    region: str = "India (Mumbai)"
    currency: str = "INR"
    note: str = Field(default="", max_length=2000)


def request_out(r: AccessRequest, db: Session) -> dict:
    t = db.get(Tenant, r.tenant_id) if r.tenant_id else None
    return {"id": r.id, "kind": r.kind, "name": r.name, "email": r.email, "organisation": r.organisation, "role": r.role,
            "role_label": ROLES.get(r.role, r.role), "tenant": {"code": t.code, "name": t.name} if t else None, "details": r.details,
            "note": r.note, "status": r.status, "decided_by": r.decided_by, "created_at": r.created_at.isoformat()}


@router.post("/access-requests", status_code=201)
def create_request(body: AccessRequestIn, db: Session = Depends(get_db)):
    tenant_id = None
    if body.kind == "join":
        t = db.scalars(select(Tenant).where(Tenant.code == (body.tenant_code or "").upper())).first()
        if not t:
            raise HTTPException(404, "Unknown tenant code")
        if body.role not in ROLES or body.role == "admin":
            raise HTTPException(422, "Choose a workspace role; tenant administrators are appointed by the provider")
        tenant_id = t.id
    else:
        if body.plan not in PLANS or body.cloud not in CLOUDS or body.region not in REGIONS:
            raise HTTPException(422, "Unknown plan, cloud or region")
    dup = db.scalars(select(AccessRequest).where(AccessRequest.email == body.email, AccessRequest.status == "Pending",
                                                 AccessRequest.kind == body.kind)).first()
    if dup:
        raise HTTPException(409, "A pending request already exists for this email")
    r = AccessRequest(kind=body.kind, tenant_id=tenant_id, name=body.name, email=body.email, organisation=body.organisation, role=body.role,
                      details={"plan": body.plan, "cloud": body.cloud, "region": body.region, "currency": body.currency} if body.kind == "new_org" else {},
                      note=body.note)
    db.add(r)
    db.flush()
    if tenant_id:
        audit.record(db, tenant_id, body.name, "public", "Access requested", f"{body.email} as {ROLES[body.role]}")
    db.commit()
    return {**request_out(r, db), "routed_to": "Tenant Admin" if body.kind == "join" else "Provider Admin"}


# ---------------------------------------------------------------------------
# tenant admin: join requests
# ---------------------------------------------------------------------------
class DecideIn(BaseModel):
    decision: str = Field(pattern="^(Approved|Rejected)$")
    role: str | None = None
    comment: str = ""


@router.get("/access-requests")
def tenant_requests(status: str | None = None, p: Principal = Depends(require("tenant:admin")), db: Session = Depends(get_db)):
    q = select(AccessRequest).where(AccessRequest.tenant_id == p.tenant_id, AccessRequest.kind == "join")
    if status:
        q = q.where(AccessRequest.status == status)
    return [request_out(r, db) for r in db.scalars(q.order_by(AccessRequest.created_at.desc()))]


@router.post("/access-requests/{rid}/decide")
def tenant_decide(rid: str, body: DecideIn, p: Principal = Depends(require("tenant:admin")), db: Session = Depends(get_db)):
    r = db.get(AccessRequest, rid)
    if not r or r.tenant_id != p.tenant_id or r.kind != "join":
        raise HTTPException(404, "Request not found")
    if r.status != "Pending":
        raise HTTPException(409, f"Request already {r.status.lower()}")
    r.status, r.decided_by, r.decided_at = body.decision, p.name, _now()
    if body.decision == "Approved":
        role = body.role or r.role
        if role not in ROLES:
            raise HTTPException(422, "Unknown role")
        if not db.scalars(select(User).where(User.tenant_id == p.tenant_id, User.email == r.email)).first():
            db.add(User(tenant_id=p.tenant_id, email=r.email, name=r.name, roles=[role]))
    audit.record(db, p.tenant_id, p.name, p.role, f"Access request {body.decision.lower()}", f"{r.email} · {ROLES.get(r.role, r.role)}",
                 {"comment": body.comment})
    db.commit()
    return request_out(r, db)


@router.get("/tenant-admin/users")
def tenant_users(p: Principal = Depends(require("tenant:admin")), db: Session = Depends(get_db)):
    return [{"id": u.id, "name": u.name, "email": u.email, "roles": u.roles} for u in
            db.scalars(select(User).where(User.tenant_id == p.tenant_id).order_by(User.created_at))]


class UserRoleIn(BaseModel):
    roles: list[str]


@router.patch("/tenant-admin/users/{uid}")
def set_roles(uid: str, body: UserRoleIn, p: Principal = Depends(require("tenant:admin")), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or u.tenant_id != p.tenant_id:
        raise HTTPException(404, "User not found")
    if not body.roles or set(body.roles) - set(ROLES):
        raise HTTPException(422, "Unknown role")
    u.roles = body.roles
    audit.record(db, p.tenant_id, p.name, p.role, "Roles changed", f"{u.email} → {', '.join(body.roles)}")
    db.commit()
    return {"id": u.id, "roles": u.roles}


# ---------------------------------------------------------------------------
# provider admin
# ---------------------------------------------------------------------------
def tenant_row(db: Session, t: Tenant) -> dict:
    sub = subscription(db, t)
    users = db.scalar(select(func.count()).select_from(User).where(User.tenant_id == t.id)) or 0
    runs = db.scalar(select(func.count()).select_from(ExecutionRun).where(ExecutionRun.tenant_id == t.id)) or 0
    tokens = db.scalar(select(func.coalesce(func.sum(ExecutionRun.tokens), 0)).where(ExecutionRun.tenant_id == t.id)) or 0
    cost = db.scalar(select(func.coalesce(func.sum(ExecutionRun.cost), 0)).where(ExecutionRun.tenant_id == t.id)) or 0
    return {"id": t.id, "code": t.code, "name": t.name, "currency": t.currency, "region": t.region, "isolation_model": t.isolation_model,
            "plan": sub.plan, "status": sub.status, "cloud": sub.cloud, "n8n_placement": sub.n8n_placement, "users": users, "runs": runs,
            "tokens": int(tokens), "model_cost": round(float(cost), 2), "created_at": t.created_at.isoformat()}


@router.get("/provider/overview")
def overview(p: Principal = Depends(provider), db: Session = Depends(get_db)):
    tenants = [tenant_row(db, t) for t in db.scalars(select(Tenant).order_by(Tenant.created_at))]
    db.commit()
    pending = db.scalar(select(func.count()).select_from(AccessRequest).where(AccessRequest.kind == "new_org", AccessRequest.status == "Pending")) or 0
    adapter = get_adapter()
    return {"tenants": tenants, "pending_org_requests": pending, "plans": PLANS,
            "runtime": {"framework": adapter.framework, "version": adapter.framework_version(), "mode": getattr(adapter, "mode", "")},
            "licence": {"n8n": "Sustainable Use License (fair-code). Internal use free; serving external tenants requires an n8n Embed licence.",
                        "aivanta": "Proprietary (your company)"}}


@router.get("/provider/requests")
def provider_requests(status: str | None = None, p: Principal = Depends(provider), db: Session = Depends(get_db)):
    q = select(AccessRequest)
    if status:
        q = q.where(AccessRequest.status == status)
    return [request_out(r, db) for r in db.scalars(q.order_by(AccessRequest.created_at.desc()))]


class ProvisionIn(BaseModel):
    code: str = Field(min_length=2, max_length=8, pattern="^[A-Za-z0-9]+$")
    name: str
    plan: str = "Growth"
    cloud: str = "AWS"
    region: str = "India (Mumbai)"
    currency: str = "INR"
    admin_email: EmailStr
    admin_name: str = "Tenant Administrator"


def provision_tenant(db: Session, body: ProvisionIn, actor: str) -> Tenant:
    if body.plan not in PLANS or body.cloud not in CLOUDS:
        raise HTTPException(422, "Unknown plan or cloud")
    if db.scalars(select(Tenant).where(Tenant.code == body.code.upper())).first():
        raise HTTPException(409, "Tenant code already exists")
    plan = PLANS[body.plan]
    t = create_tenant(db, body.code.upper(), body.name, body.currency, body.region, plan["isolation"])
    db.add(Subscription(tenant_id=t.id, plan=body.plan, status="Active", cloud=body.cloud, n8n_placement=plan["n8n"], admin_email=body.admin_email))
    db.add(User(tenant_id=t.id, email=body.admin_email, name=body.admin_name, roles=["admin"]))
    db.add(Project(tenant_id=t.id, code=f"{t.code}-0001", client=body.name, name="Pilot proposal", scope="Pilot engagement used to validate the RFP-to-SOW workflow.",
                   region=t.region, currency=t.currency, owner=body.admin_name, estimate_inputs=DEFAULT_ESTIMATE, workload={**DEFAULT_WORKLOAD, "region": t.region},
                   clarifications=[{"question": "Confirm integration scope for phase 1", "open": True}]))
    add_graph(db, t, "RFP_SOW", "RFP-to-SOW", ["dev"], by=actor)
    audit.record(db, t.id, actor, "provider", "Tenant provisioned", f"{t.name} · {body.plan} · {body.cloud} · {t.region}",
                 {"n8n_placement": plan["n8n"], "isolation": plan["isolation"]})
    return t


@router.post("/provider/tenants", status_code=201)
def provider_provision(body: ProvisionIn, p: Principal = Depends(provider_write), db: Session = Depends(get_db)):
    t = provision_tenant(db, body, p.name)
    db.commit()
    return tenant_row(db, t)


class TenantUpdate(BaseModel):
    plan: str | None = None
    status: str | None = Field(default=None, pattern="^(Active|Suspended)$")
    cloud: str | None = None


@router.patch("/provider/tenants/{tid}")
def provider_update(tid: str, body: TenantUpdate, p: Principal = Depends(provider_write), db: Session = Depends(get_db)):
    t = db.get(Tenant, tid)
    if not t:
        raise HTTPException(404, "Tenant not found")
    sub = subscription(db, t)
    changes = body.model_dump(exclude_none=True)
    if "plan" in changes and changes["plan"] not in PLANS:
        raise HTTPException(422, "Unknown plan")
    if "cloud" in changes and changes["cloud"] not in CLOUDS:
        raise HTTPException(422, "Unknown cloud")
    for k, v in changes.items():
        setattr(sub, k, v)
    if "plan" in changes:
        sub.n8n_placement = PLANS[changes["plan"]]["n8n"]
    _cache.pop(tid, None)
    audit.record(db, t.id, p.name, "provider", "Subscription changed", t.name, changes)
    db.commit()
    return tenant_row(db, t)


@router.post("/provider/requests/{rid}/decide")
def provider_decide(rid: str, body: DecideIn, p: Principal = Depends(provider_write), db: Session = Depends(get_db)):
    r = db.get(AccessRequest, rid)
    if not r or r.kind != "new_org":
        raise HTTPException(404, "Request not found")
    if r.status != "Pending":
        raise HTTPException(409, f"Request already {r.status.lower()}")
    r.status, r.decided_by, r.decided_at = body.decision, p.name, _now()
    out: dict = {}
    if body.decision == "Approved":
        code = re.sub(r"[^A-Z0-9]", "", r.organisation.upper())[:6] or "NEW"
        while db.scalars(select(Tenant).where(Tenant.code == code)).first():
            code = (code[:5] + str(int(time.time()) % 10))[:8]
        d = r.details or {}
        t = provision_tenant(db, ProvisionIn(code=code, name=r.organisation, plan=d.get("plan", "Growth"), cloud=d.get("cloud", "AWS"),
                                             region=d.get("region", "India (Mumbai)"), currency=d.get("currency", "INR"), admin_email=r.email,
                                             admin_name=r.name), p.name)
        r.tenant_id = t.id
        out = {"tenant": tenant_row(db, t)}
    db.commit()
    return {**request_out(r, db), **out}
