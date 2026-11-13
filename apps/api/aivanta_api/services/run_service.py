"""Run coordination: create runs, build runtime contexts, persist events,
approvals and artifacts. Runtime-agnostic: works with whichever adapter the
edition ships (LangGraph in Conductor, AutoGen in Ensemble)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from aivanta_connectors import ToolGateway, hybrid_search
from aivanta_graph import CanvasGraph
from aivanta_runtime import Decision, LLMSettings, RunContext, RunOutcome, get_adapter
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .. import audit
from ..config import get_settings
from ..db import session_scope
from ..models import AgentDefinition, Approval, Artifact, ExecutionRun, Project, RunEvent, Tenant
from .backend import DbToolBackend
from .common import approved_tools, cloud_compare, cloud_monthly, price, project_dict

log = logging.getLogger("aivanta.runs")
_locks: dict[str, asyncio.Lock] = {}
_tasks: set[asyncio.Task] = set()

ARTIFACT_TYPES = {"requirements.v1": ("Compliance matrix", "architect"), "brd.v1": ("BRD", "architect"), "sow.v1": ("SOW", "reviewer"),
                  "architecture.v1": ("Architecture proposal", "architect"), "effort.v1": ("Effort plan", "pmo"),
                  "staffing.v1": ("Staffing plan", "pmo"), "review.v1": ("Review findings", "reviewer"), "tech_matrix.v1": ("Technology decision matrix", "architect")}
NODE_STATE = {"node_started": "running", "node_succeeded": "succeeded", "node_skipped": "skipped", "node_failed": "failed",
              "approval_requested": "approval"}


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------
def build_context(run_id: str) -> RunContext:
    with session_scope() as db:
        run = db.get(ExecutionRun, run_id)
        tenant = db.get(Tenant, run.tenant_id)
        project = db.get(Project, run.project_id)
        pdict = project_dict(project)
        pdict["rfp_file"] = None
        from ..models import Document
        doc = db.scalars(select(Document).where(Document.project_id == project.id).order_by(Document.created_at.desc())).first()
        if doc:
            pdict["rfp_file"] = doc.filename
        tools = {k for k, v in approved_tools(db, tenant.id).items() if v}
        overrides = {}
        for d in db.scalars(select(AgentDefinition).where(AgentDefinition.tenant_id == tenant.id).order_by(AgentDefinition.version)):
            overrides[d.template_id] = {"instructions": d.instructions, "version": d.version}
        tenant_snapshot = {c.name: getattr(tenant, c.name) for c in Tenant.__table__.columns}
        graph = CanvasGraph.model_validate(run.graph_snapshot)
        ctx_vals = dict(tenant_id=tenant.id, graph_version=run.graph_version, mode=run.mode, idem=run.idempotency_prefix,
                        workload=project.workload or {}, est=project.estimate_inputs or {})
    tenant_obj = Tenant(**tenant_snapshot)
    backend = DbToolBackend()

    async def emit(kind: str, node_id: str | None, data: dict[str, Any]) -> None:
        await asyncio.to_thread(_persist_event, run_id, kind, node_id, data)

    def pricing_hook(upstream: dict, cfg: dict) -> dict:
        effort = next((v for v in upstream.values() if isinstance(v, dict) and "role_lines" in v), None)
        levers = next((v for v in upstream.values() if isinstance(v, dict) and "target_margin_pct" in v), {})
        sizing = next((v for v in upstream.values() if isinstance(v, dict) and "workload" in v), None)
        est = ctx_vals["est"]
        lines = (effort or {}).get("role_lines") or est.get("role_lines") or []
        workload = (sizing or {}).get("workload") or ctx_vals["workload"]
        provider = (sizing or {}).get("preferred_provider") or est.get("provider", "azure")
        inputs = {"role_lines": [{"role": ln["role"], "fte": ln["fte"], "months": ln["months"]} for ln in lines],
                  "cloud_monthly": str(cloud_monthly(tenant_obj, workload, provider)) if workload else "0",
                  "target_margin_pct": levers.get("target_margin_pct", est.get("target_margin_pct", 30)),
                  "discount_pct": levers.get("discount_pct", est.get("discount_pct", 0)),
                  "overhead_pct": est.get("overhead_pct", 8), "contingency_pct": est.get("contingency_pct", 10),
                  "licenses": est.get("licenses", 0), "travel": est.get("travel", 0)}
        out = price(tenant_obj, inputs)
        out["inputs"] = inputs
        out["provider"] = provider
        return out

    def retrieve(query: str, k: int) -> list[dict]:
        return hybrid_search(query, backend.project_chunks(ctx_vals["tenant_id"], pdict["id"]), top_k=k)

    def is_cancelled() -> bool:
        with session_scope() as db:
            return bool(db.get(ExecutionRun, run_id).cancel_requested)

    def load_state() -> dict:
        with session_scope() as db:
            return dict(db.get(ExecutionRun, run_id).state or {})

    def save_state(state: dict) -> None:
        with session_scope() as db:
            r = db.get(ExecutionRun, run_id)
            r.state = _jsonable(state)
            r.node_status = dict(state.get("status", r.node_status or {}))

    return RunContext(run_id=run_id, tenant_id=ctx_vals["tenant_id"], project=pdict, graph=graph, graph_version=ctx_vals["graph_version"],
                      mode=ctx_vals["mode"], gateway=ToolGateway(backend), approved_tools=tools, emit=emit, pricing=pricing_hook,
                      cloud=lambda w: cloud_compare(tenant_obj, w), retrieve=retrieve, llm=LLMSettings.from_env(), is_cancelled=is_cancelled,
                      load_state=load_state, save_state=save_state, agent_overrides=overrides, idempotency_prefix=ctx_vals["idem"],
                      fx_rate=float(tenant_obj.fx_rate) if tenant_obj.currency != "USD" else 1.0)


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


# ---------------------------------------------------------------------------
# event persistence and side effects
# ---------------------------------------------------------------------------
def _persist_event(run_id: str, kind: str, node_id: str | None, data: dict) -> None:
    dedupe = f"{kind}:{node_id}" if kind in ("approval_requested", "approval_decided") else f"{kind}:{node_id}:{uuid.uuid4().hex}"
    try:
        with session_scope() as db:
            run = db.get(ExecutionRun, run_id)
            db.add(RunEvent(tenant_id=run.tenant_id, run_id=run_id, type=kind, node_id=node_id, data=_jsonable(data), dedupe_key=dedupe))
            if node_id and kind in NODE_STATE:
                ns = dict(run.node_status or {})
                ns[node_id] = NODE_STATE[kind]
                run.node_status = ns
            if kind == "approval_requested":
                exists = db.scalars(select(Approval).where(Approval.run_id == run_id, Approval.node_id == node_id)).first()
                if not exists:
                    db.add(Approval(tenant_id=run.tenant_id, run_id=run_id, node_id=node_id, project_id=run.project_id,
                                    kind=data.get("name") or node_id, approver_role=data.get("approver_role") or "finance",
                                    evidence=data.get("evidence") or "", requested_by=run.started_by, sla_hours=int(data.get("sla_hours") or 24)))
                    audit.record(db, run.tenant_id, run.started_by, "system", "Approval requested", f"{run_id} · {data.get('name')}")
    except IntegrityError:
        pass  # duplicate approval event after a LangGraph node replay


def _upsert_artifacts(db, run: ExecutionRun, outputs: dict, graph: CanvasGraph) -> None:
    for node_id, out in outputs.items():
        node = graph.node(node_id)
        if not node or not isinstance(out, dict):
            continue
        kind, reviewer = None, "architect"
        if node.type == "agent":
            kind, reviewer = ARTIFACT_TYPES.get(node.config.get("output_schema"), (None, None))
        elif node.type == "calc" and "result" in out:
            kind, reviewer = "Pricing worksheet", "finance"
        elif node.type == "calc" and "cloud" in out:
            kind, reviewer = "Cloud cost scenarios", "finance"
        if not kind:
            continue
        art = db.scalars(select(Artifact).where(Artifact.project_id == run.project_id, Artifact.type == kind, Artifact.run_id == run.id)).first()
        sources = []
        for r in out.get("requirements", []):
            sources.append(f"{r['source']['document']} {r['source']['locator']}")
        if art:
            art.content = _jsonable(out)
            continue
        latest = db.scalar(select(func.max(Artifact.version)).where(Artifact.project_id == run.project_id, Artifact.type == kind)) or 0
        db.add(Artifact(tenant_id=run.tenant_id, project_id=run.project_id, run_id=run.id, graph_version=run.graph_version, type=kind,
                        version=latest + 1, content=_jsonable(out), source_ids=sorted(set(sources))[:200] or [f"run {run.id}"],
                        reviewer_role=reviewer, approval_state="simulation" if run.mode == "simulation" else "in_review",
                        storage_uri=f"objects/{run.tenant_id}/{run.project_id}/{kind.lower().replace(' ', '-')}/v{latest + 1}",
                        created_by=f"{run.runtime} run {run.id}"))


def _persist_outcome(run_id: str, outcome: RunOutcome) -> None:
    with session_scope() as db:
        run = db.get(ExecutionRun, run_id)
        run.status = outcome.status
        merged = dict(run.node_status or {})
        merged.update(outcome.node_status)
        run.node_status = merged
        run.outputs = _jsonable(outcome.outputs)
        run.tokens = int(outcome.metrics.get("tokens", 0))
        run.cost = float(outcome.metrics.get("cost", 0))
        run.error = outcome.error
        run.pending_action = None
        if outcome.status in ("succeeded", "failed", "cancelled"):
            run.ended_at = _now()
        _upsert_artifacts(db, run, outcome.outputs, CanvasGraph.model_validate(run.graph_snapshot))
        db.add(RunEvent(tenant_id=run.tenant_id, run_id=run_id, type=f"run_{outcome.status}" if outcome.status != "awaiting_approval" else "run_paused",
                        node_id=None, data={"error": outcome.error, "metrics": outcome.metrics}, dedupe_key=f"outcome:{uuid.uuid4().hex}"))
        audit.record(db, run.tenant_id, run.started_by, "system", f"Run {outcome.status.replace('_', ' ')}", f"{run.id} · {run.graph_version}",
                     {"tokens": run.tokens, "error": outcome.error})


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------
def decided_approvals(run_id: str) -> dict[str, Decision]:
    with session_scope() as db:
        out = {}
        for a in db.scalars(select(Approval).where(Approval.run_id == run_id, Approval.status.in_(["Approved", "Rejected"]))):
            out[a.node_id] = Decision(decision=a.status, by=a.decided_by or "", role=a.approver_role, comment=a.comment or "")
        return out


async def execute(run_id: str, action: str) -> RunOutcome:
    lock = _locks.setdefault(run_id, asyncio.Lock())
    async with lock:
        adapter = get_adapter()
        ctx = await asyncio.to_thread(build_context, run_id)
        with session_scope() as db:
            db.get(ExecutionRun, run_id).status = "running"
        try:
            if action == "start":
                outcome = await adapter.start(ctx)
            elif action == "resume":
                outcome = await adapter.resume(ctx, decided_approvals(run_id))
            elif action == "retry":
                outcome = await adapter.retry_failed(ctx)
            else:
                raise ValueError(action)
        except Exception as exc:  # unexpected runtime error: keep state for inspection
            log.exception("run %s crashed", run_id)
            outcome = RunOutcome(status="failed", error=f"{type(exc).__name__}: {exc}")
        await asyncio.to_thread(_persist_outcome, run_id, outcome)
        return outcome


def dispatch(run_id: str, action: str, background) -> None:
    """Execute inline as a FastAPI background task, or hand the run to the worker process
    (RUN_EXECUTION=worker, required for multi-replica deployments)."""
    if get_settings().run_execution == "worker":
        with session_scope() as db:
            r = db.get(ExecutionRun, run_id)
            r.pending_action = action
            r.status = "queued"
        return
    background.add_task(execute, run_id, action)
