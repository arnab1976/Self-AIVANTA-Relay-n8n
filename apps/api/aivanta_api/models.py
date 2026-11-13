"""Persistent entities (blueprint section 10). Every row is tenant-scoped."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    region: Mapped[str] = mapped_column(String(64), default="India (Mumbai)")
    isolation_model: Mapped[str] = mapped_column(String(64), default="schema-per-tenant")
    identity_provider: Mapped[str] = mapped_column(String(64), default="Entra ID (OIDC)")
    margin_floor_pct: Mapped[float] = mapped_column(Float, default=22)
    discount_limit_pct: Mapped[float] = mapped_column(Float, default=10)
    allowed_models: Mapped[list] = mapped_column(JSON, default=lambda: ["enterprise-reasoning", "enterprise-fast", "local-open-weight"])
    rate_card: Mapped[dict] = mapped_column(JSON, default=dict)
    rate_card_version: Mapped[str] = mapped_column(String(40), default="RC-1")
    fx_rate: Mapped[float] = mapped_column(Float, default=84.0)
    fx_version: Mapped[str] = mapped_column(String(40), default="FX-1")
    price_snapshot_date: Mapped[str] = mapped_column(String(10), default="2026-10-20")
    integrations: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    roles: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    client: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str] = mapped_column(String(64), default="BFSI")
    deal_stage: Mapped[str] = mapped_column(String(32), default="RFP received")
    delivery_model: Mapped[str] = mapped_column(String(32), default="Fixed price")
    region: Mapped[str] = mapped_column(String(64), default="India (Mumbai)")
    scope: Mapped[str] = mapped_column(Text, default="")
    deadline: Mapped[str | None] = mapped_column(String(10), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    classification: Mapped[str] = mapped_column(String(32), default="Confidential")
    owner: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    clarifications: Mapped[list] = mapped_column(JSON, default=list)
    estimate_inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    workload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_uri: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    pages: Mapped[int] = mapped_column(Integer, default=0)
    pii_redactions: Mapped[dict] = mapped_column(JSON, default=dict)
    scan_engine: Mapped[str] = mapped_column(String(40), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DocumentChunk(Base):
    """Embedding stored as JSON for portability. On PostgreSQL, migrate to a pgvector column (docs/architecture/data-contracts.md)."""
    __tablename__ = "document_chunks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(JSON)


class ToolPolicy(Base):
    __tablename__ = "tool_policies"
    __table_args__ = (UniqueConstraint("tenant_id", "tool_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    tool_id: Mapped[str] = mapped_column(String(64))
    approved: Mapped[bool] = mapped_column(Boolean, default=True)


class AgentDefinition(Base):
    __tablename__ = "agent_definitions"
    __table_args__ = (UniqueConstraint("tenant_id", "template_id", "version"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    template_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    instructions: Mapped[str] = mapped_column(Text)
    model_profile: Mapped[str] = mapped_column(String(64))
    tools: Mapped[list] = mapped_column(JSON, default=list)
    policies: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CanvasGraphRow(Base):
    __tablename__ = "canvas_graphs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    template: Mapped[str] = mapped_column(String(32), default="BLANK")
    draft: Mapped[dict] = mapped_column(JSON)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class GraphVersion(Base):
    """Immutable published version of a canvas graph."""
    __tablename__ = "graph_versions"
    __table_args__ = (UniqueConstraint("graph_id", "version"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    graph_id: Mapped[str] = mapped_column(ForeignKey("canvas_graphs.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(32))
    environment: Mapped[str] = mapped_column(String(16), default="dev")
    published_by: Mapped[str] = mapped_column(String(200))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExecutionRun(Base):
    __tablename__ = "execution_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    graph_id: Mapped[str] = mapped_column(ForeignKey("canvas_graphs.id"), index=True)
    graph_version: Mapped[str] = mapped_column(String(16))  # "v3" or "draft"
    graph_snapshot: Mapped[dict] = mapped_column(JSON)
    mode: Mapped[str] = mapped_column(String(16), default="published")
    runtime: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    pending_action: Mapped[str | None] = mapped_column(String(24), nullable=True)  # start | resume | retry (worker mode)
    trace_id: Mapped[str] = mapped_column(String(32), default=_id)
    idempotency_prefix: Mapped[str] = mapped_column(String(64), default=_id)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    node_status: Mapped[dict] = mapped_column(JSON, default=dict)
    outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started_by: Mapped[str] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "dedupe_key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("execution_runs.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("execution_runs.id"), nullable=True, index=True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(120))
    approver_role: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="Pending")
    requested_by: Mapped[str] = mapped_column(String(200), default="")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    sla_hours: Mapped[int] = mapped_column(Integer, default=24)
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    graph_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    type: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[dict] = mapped_column(JSON)
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    reviewer_role: Mapped[str] = mapped_column(String(32), default="architect")
    approval_state: Mapped[str] = mapped_column(String(24), default="in_review")
    storage_uri: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Estimate(Base):
    __tablename__ = "estimates"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    inputs: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    scenarios: Mapped[dict] = mapped_column(JSON, default=dict)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    currency: Mapped[str] = mapped_column(String(3))
    selling_price: Mapped[str] = mapped_column(String(32))
    margin_pct: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ToolInvocation(Base):
    """Idempotency ledger for external actions."""
    __tablename__ = "tool_invocations"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    run_id: Mapped[str] = mapped_column(String(32))
    node_id: Mapped[str] = mapped_column(String(64))
    tool_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request: Mapped[dict] = mapped_column(JSON)
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditEvent(Base):
    """Append-only, hash-chained audit trail per tenant."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(32), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    actor: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(120))
    entity: Mapped[str] = mapped_column(String(300))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
