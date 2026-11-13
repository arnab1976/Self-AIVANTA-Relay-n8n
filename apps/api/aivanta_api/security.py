"""Authentication (dev tokens or OIDC / Entra ID) and RBAC."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request, status

from .config import get_settings

ROLES = {
    "presales": "Presales Engineer", "architect": "Solution Architect", "aieng": "AI Engineer", "ea": "Enterprise Architect",
    "finance": "Finance / Commercial", "pmo": "PMO / Delivery", "reviewer": "Governance Reviewer", "admin": "Platform Administrator",
}

PERMISSIONS: dict[str, set[str]] = {
    "project:write": {"presales", "architect", "pmo"},
    "graph:edit": {"presales", "architect", "aieng"},
    "graph:publish": {"architect", "aieng", "ea"},
    "graph:promote": {"ea", "admin"},
    "run:start": {"presales", "architect", "aieng", "pmo"},
    "tool:approve": {"aieng", "ea", "admin"},
    "agent:edit": {"aieng"},
    "pricing:edit": {"finance"},
    "estimate:write": {"finance", "presales", "pmo"},
    "artifact:review": {"reviewer", "architect", "finance"},
    "tenant:admin": {"admin"},
    "audit:read": set(ROLES),
}


@dataclass
class Principal:
    user_id: str
    tenant_id: str
    email: str
    name: str
    roles: list[str]

    @property
    def role(self) -> str:
        return self.roles[0] if self.roles else "presales"

    def can(self, perm: str) -> bool:
        return bool(set(self.roles) & PERMISSIONS.get(perm, set()))


def issue_dev_token(user_id: str, tenant_id: str, email: str, name: str, roles: list[str]) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": user_id, "tid": tenant_id, "email": email, "name": name, "roles": roles, "iat": now,
               "exp": now + timedelta(minutes=s.jwt_ttl_minutes), "iss": "aivanta-dev"}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


@lru_cache
def _jwks_client():
    return jwt.PyJWKClient(get_settings().oidc_jwks_url)


def _role_map() -> dict[str, str]:
    """ROLE_GROUP_MAP='{"<entra-group-id>": "finance", ...}' maps IdP groups/app roles to AIVANTA roles."""
    try:
        return json.loads(os.getenv("ROLE_GROUP_MAP", "{}"))
    except json.JSONDecodeError:
        return {}


def decode_token(token: str) -> dict:
    s = get_settings()
    if s.auth_mode == "dev":
        return jwt.decode(token, s.jwt_secret, algorithms=["HS256"], issuer="aivanta-dev")
    key = _jwks_client().get_signing_key_from_jwt(token).key
    return jwt.decode(token, key, algorithms=["RS256"], audience=s.oidc_audience, issuer=s.oidc_issuer)


def principal_from_claims(claims: dict) -> Principal:
    s = get_settings()
    if s.auth_mode == "dev":
        return Principal(claims["sub"], claims["tid"], claims.get("email", ""), claims.get("name", ""), list(claims.get("roles", [])))
    mapping = _role_map()
    raw = list(claims.get(s.oidc_roles_claim, [])) + list(claims.get("groups", []))
    roles = sorted({mapping.get(r, r) for r in raw} & set(ROLES))
    tenant = claims.get(s.oidc_tenant_claim)
    if not tenant:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Token has no AIVANTA tenant claim")
    return Principal(claims.get("oid") or claims["sub"], tenant, claims.get("preferred_username", ""), claims.get("name", ""), roles)


def current_principal(request: Request) -> Principal:
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("access_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    try:
        claims = decode_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc
    return principal_from_claims(claims)


def require(perm: str):
    def dep(p: Principal = Depends(current_principal)) -> Principal:
        if not p.can(perm):
            allowed = ", ".join(ROLES[r] for r in sorted(PERMISSIONS.get(perm, set())))
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"'{perm}' requires one of: {allowed}")
        return p
    return dep
