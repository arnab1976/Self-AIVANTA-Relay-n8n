"""ToolBackend implementation over the AIVANTA database (tenant + project scoped)."""
from __future__ import annotations

from aivanta_connectors.gateway import ToolBackend
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db import session_scope
from ..models import Document, DocumentChunk, Project, ToolInvocation

SAMPLE_AVAILABILITY = [
    {"name": "Ananya Rao", "role": "Solution Architect", "available_pct": 40},
    {"name": "Priya Nair", "role": "Frontend Engineer", "available_pct": 80},
    {"name": "Karthik Reddy", "role": "Python / AI Engineer", "available_pct": 60},
    {"name": "Divya Kulkarni", "role": "Platform Engineer", "available_pct": 50},
    {"name": "Arjun Pillai", "role": "QA Engineer", "available_pct": 70},
    {"name": "Rohan Das", "role": "Business Analyst", "available_pct": 80},
]


class DbToolBackend(ToolBackend):
    def read_document_text(self, tenant_id: str, project_id: str) -> dict:
        with session_scope() as db:
            doc = db.scalars(select(Document).where(Document.tenant_id == tenant_id, Document.project_id == project_id)
                             .order_by(Document.created_at.desc())).first()
            if not doc:
                proj = db.get(Project, project_id)
                return {"filename": None, "pages": 0, "text": (proj.scope if proj and proj.tenant_id == tenant_id else "")}
            return {"filename": doc.filename, "pages": doc.pages, "text": doc.text, "document_id": doc.id,
                    "storage_uri": doc.storage_uri, "pii_redactions": doc.pii_redactions}

    def project_metadata(self, tenant_id: str, project_id: str) -> dict:
        with session_scope() as db:
            p = db.get(Project, project_id)
            if not p or p.tenant_id != tenant_id:
                return {}
            return {"code": p.code, "client": p.client, "name": p.name, "industry": p.industry, "deal_stage": p.deal_stage, "region": p.region}

    def project_chunks(self, tenant_id: str, project_id: str) -> list[dict]:
        with session_scope() as db:
            rows = db.scalars(select(DocumentChunk).where(DocumentChunk.tenant_id == tenant_id, DocumentChunk.project_id == project_id)).all()
            docs = {d.id: d.filename for d in db.scalars(select(Document).where(Document.project_id == project_id))}
            return [{"id": r.id, "text": r.text, "embedding": r.embedding, "source": f"{docs.get(r.document_id, 'document')} chunk {r.ordinal}"} for r in rows]

    def staff_availability(self, tenant_id: str) -> list[dict]:
        return SAMPLE_AVAILABILITY

    def idempotency_get(self, tenant_id: str, key: str) -> dict | None:
        with session_scope() as db:
            row = db.scalars(select(ToolInvocation).where(ToolInvocation.tenant_id == tenant_id, ToolInvocation.idempotency_key == key)).first()
            return row.response if row else None

    def idempotency_put(self, tenant_id, key, run_id, node_id, tool_id, request, response) -> None:
        try:
            with session_scope() as db:
                db.add(ToolInvocation(tenant_id=tenant_id, idempotency_key=key, run_id=run_id, node_id=node_id, tool_id=tool_id,
                                      request=request, response=response))
        except IntegrityError:
            pass  # concurrent duplicate: first writer wins
