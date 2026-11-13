"""Hash-chained, append-only audit trail."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditEvent


def _digest(prev: str, tenant_id: str, actor: str, action: str, entity: str, detail: dict) -> str:
    raw = json.dumps([prev, tenant_id, actor, action, entity, detail], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def record(db: Session, tenant_id: str, actor: str, role: str, action: str, entity: str, detail: dict | None = None) -> AuditEvent:
    last = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.id.desc()).limit(1)).first()
    prev = last.hash if last else "0" * 64
    detail = detail or {}
    ev = AuditEvent(tenant_id=tenant_id, actor=actor, role=role, action=action, entity=entity, detail=detail,
                    prev_hash=prev, hash=_digest(prev, tenant_id, actor, action, entity, detail))
    db.add(ev)
    db.flush()
    return ev


def verify_chain(db: Session, tenant_id: str) -> dict:
    prev = "0" * 64
    n = 0
    for ev in db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.id)):
        if ev.prev_hash != prev or ev.hash != _digest(prev, tenant_id, ev.actor, ev.action, ev.entity, ev.detail or {}):
            return {"valid": False, "broken_at": ev.id, "checked": n}
        prev = ev.hash
        n += 1
    return {"valid": True, "checked": n, "head": prev}
