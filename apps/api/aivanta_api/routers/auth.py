from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..models import Tenant, User
from ..security import PERMISSIONS, ROLES, Principal, current_principal, issue_dev_token

router = APIRouter(prefix="/auth", tags=["auth"])


class DevLogin(BaseModel):
    tenant_code: str
    role: str
    name: str = "Demo User"
    email: str | None = None


@router.get("/tenants")
def login_tenants(db: Session = Depends(get_db)):
    """Tenant picker for the dev sign-in screen. Disabled when AUTH_MODE=oidc."""
    if get_settings().auth_mode != "dev":
        return []
    return [{"code": t.code, "name": t.name, "region": t.region, "currency": t.currency, "isolation_model": t.isolation_model}
            for t in db.scalars(select(Tenant).order_by(Tenant.created_at))]


@router.post("/dev-login")
def dev_login(body: DevLogin, db: Session = Depends(get_db)):
    if get_settings().auth_mode != "dev":
        raise HTTPException(404, "Dev login is disabled; sign in with your identity provider.")
    if body.role not in ROLES:
        raise HTTPException(422, f"Unknown role. Use one of: {', '.join(ROLES)}")
    tenant = db.scalars(select(Tenant).where(Tenant.code == body.tenant_code)).first()
    if not tenant:
        raise HTTPException(404, "Unknown tenant")
    email = body.email or f"{body.name.lower().replace(' ', '.')}@{tenant.code.lower()}.example"
    user = db.scalars(select(User).where(User.tenant_id == tenant.id, User.email == email)).first()
    if not user:
        user = User(tenant_id=tenant.id, email=email, name=body.name, roles=[body.role])
        db.add(user)
    else:
        user.roles = [body.role]
        user.name = body.name
    db.flush()
    audit.record(db, tenant.id, body.name, body.role, f"Signed in via {tenant.identity_provider}", tenant.name)
    db.commit()
    return {"token": issue_dev_token(user.id, tenant.id, email, body.name, [body.role]),
            "user": {"id": user.id, "name": user.name, "email": email, "roles": [body.role]},
            "tenant": {"id": tenant.id, "code": tenant.code, "name": tenant.name}}


@router.get("/me")
def me(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    t = db.get(Tenant, p.tenant_id)
    if not t:
        # Stale JWT after DB reseed / tenant wipe — force the web client to re-login.
        raise HTTPException(401, "Tenant no longer exists; sign in again")
    return {"user": {"id": p.user_id, "name": p.name, "email": p.email, "roles": p.roles, "role_labels": [ROLES.get(r, r) for r in p.roles]},
            "tenant": {"id": t.id, "code": t.code, "name": t.name, "currency": t.currency},
            "permissions": sorted(k for k in PERMISSIONS if p.can(k))}
