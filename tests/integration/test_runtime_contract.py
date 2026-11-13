"""Runtime contract tests. Identical in Conductor (LangGraph) and Ensemble (AutoGen):
both editions must produce the same outcomes for the same canvas graph."""
from __future__ import annotations

import pytest
from aivanta_connectors import ToolGateway, load_registry
from aivanta_graph import ValidationPolicy, ToolPolicy, template_graph, validate
from aivanta_pricing import PricingInput, compute
from aivanta_runtime import Decision, LLMSettings, RunContext, get_adapter

RATES = {"Solution Architect": 320000, "Frontend Engineer": 170000, "Python / AI Engineer": 230000, "Platform Engineer": 190000,
         "QA Engineer": 120000, "Business Analyst": 150000, "Security Reviewer": 260000, "Project Manager": 240000}


class FakeBackend:
    def __init__(self):
        self.idem = {}

    def read_document_text(self, tenant_id, project_id):
        return {"filename": "RFP_Test.txt", "pages": 1, "text": "The platform shall support SSO. The system must respond within 2 seconds. Users should export reports."}

    def project_metadata(self, tenant_id, project_id):
        return {"id": project_id, "client": "Test Bank"}

    def project_chunks(self, tenant_id, project_id):
        return []

    def staff_availability(self, tenant_id):
        return [{"name": "Asha", "role": "Solution Architect", "available_pct": 60}]

    def idempotency_get(self, tenant_id, key):
        return self.idem.get(key)

    def idempotency_put(self, tenant_id, key, run_id, node_id, tool_id, request, response):
        self.idem[key] = response


def pricing_hook(upstream, cfg):
    effort = next(v for v in upstream.values() if isinstance(v, dict) and "role_lines" in v)
    inp = PricingInput.from_dict({"role_lines": effort["role_lines"], "target_margin_pct": 30, "currency": "INR"}, RATES)
    return {"result": compute(inp).to_dict(), "flags": []}


def make_ctx(graph, run_id, open_clar=True, events=None, store=None, cancelled=lambda: False):
    events = events if events is not None else []
    store = store if store is not None else {}

    async def emit(kind, node_id, data):
        events.append((kind, node_id))

    registry = load_registry()
    return RunContext(
        run_id=run_id, tenant_id="t1",
        project={"id": "p1", "code": "PRJ-1", "client": "Test Bank", "name": "Test", "industry": "BFSI", "region": "India (Mumbai)",
                 "rfp_file": "RFP_Test.txt", "clarifications": [{"question": "Scope of migration?", "open": open_clar}]},
        graph=graph, graph_version="v1", mode="published", gateway=ToolGateway(FakeBackend(), registry),
        approved_tools={k for k, v in registry.items() if v.approved}, emit=emit, pricing=pricing_hook,
        cloud=lambda w: {"providers": {}}, retrieve=lambda q, k: [], llm=LLMSettings(provider="mock"),
        is_cancelled=cancelled, load_state=lambda: store.get("s"), save_state=lambda s: store.__setitem__("s", s),
    ), events, store


def approve(role="finance"):
    return Decision(decision="Approved", by="tester", role=role)


def test_template_is_valid():
    registry = load_registry()
    rep = validate(template_graph("RFP_SOW"), ValidationPolicy(tools={k: ToolPolicy(v.approved, v.external) for k, v in registry.items()}))
    assert rep.ok, rep.summary()


@pytest.mark.asyncio
async def test_rfp_to_sow_with_gaps_pauses_at_each_gate():
    adapter = get_adapter()
    graph = template_graph("RFP_SOW")
    ctx, events, _ = make_ctx(graph, "run-gaps")
    out = await adapter.start(ctx)
    assert out.status == "awaiting_approval"
    assert [p["node_id"] for p in out.pending_approvals] == ["clar"]
    assert out.node_status["gap"] == "succeeded"
    out = await adapter.resume(ctx, {"clar": approve("presales")})
    assert out.status == "awaiting_approval" and out.pending_approvals[0]["node_id"] == "capp"
    assert out.outputs["price"]["result"]["selling_price"]
    out = await adapter.resume(ctx, {"capp": approve()})
    assert out.pending_approvals[0]["node_id"] == "final"
    out = await adapter.resume(ctx, {"final": approve("reviewer")})
    assert out.status == "succeeded", out.error
    assert out.node_status["end"] == "succeeded"
    assert ("route_selected", "gap") in events
    reqs = out.outputs["rfp"]["requirements"]
    assert len(reqs) == 3 and all(r["source"]["document"] for r in reqs)  # extracted from the RFP text


@pytest.mark.asyncio
async def test_no_gaps_skips_clarification_branch():
    adapter = get_adapter()
    ctx, events, _ = make_ctx(template_graph("RFP_SOW"), "run-nogaps", open_clar=False)
    # RFP mock produces no clarifications when the project has none open
    out = await adapter.start(ctx)
    assert out.node_status["clar"] == "skipped"
    assert out.node_status["brd"] == "succeeded" and out.node_status["arch"] == "succeeded"
    assert out.pending_approvals[0]["node_id"] == "capp"


@pytest.mark.asyncio
async def test_rejection_fails_run():
    adapter = get_adapter()
    ctx, _, _ = make_ctx(template_graph("CLOUD_REVIEW"), "run-reject")
    ctx.cloud = lambda w: {"providers": {"aws": {}}}
    out = await adapter.start(ctx)
    assert out.pending_approvals[0]["node_id"] == "fapp"
    out = await adapter.resume(ctx, {"fapp": Decision(decision="Rejected", by="cfo", role="finance", comment="Too high")})
    assert out.status == "failed"
    assert out.node_status["end"] == "skipped"


@pytest.mark.asyncio
async def test_transient_failure_retries_and_hard_failure_resumes():
    adapter = get_adapter()
    graph = template_graph("CLOUD_REVIEW")
    graph.node("tech").config["fail_simulation"] = True           # retry budget 2 -> recovers
    ctx, events, _ = make_ctx(graph, "run-retry")
    out = await adapter.start(ctx)
    assert ("node_retry", "tech") in events and out.status == "awaiting_approval"

    graph2 = template_graph("CLOUD_REVIEW")
    graph2.node("fin").config.update(fail_simulation=True, retry=0)  # no retries -> run fails
    ctx2, events2, _ = make_ctx(graph2, "run-fail")
    out = await adapter.start(ctx2)
    assert out.status == "failed" and out.node_status.get("fin") in ("failed", None)
    assert out.node_status["tech"] == "succeeded"
    started_before = sum(1 for e in events2 if e == ("node_started", "tech"))
    out = await adapter.retry_failed(ctx2)
    assert out.status == "awaiting_approval"
    assert sum(1 for e in events2 if e == ("node_started", "tech")) == started_before  # completed steps not repeated


@pytest.mark.asyncio
async def test_external_action_is_idempotent():
    adapter = get_adapter()
    graph = template_graph("RES_DEPLOY")
    ctx, _, _ = make_ctx(graph, "run-idem")
    out = await adapter.start(ctx)
    out = await adapter.resume(ctx, {"sapp": approve("pmo")})
    assert out.status == "succeeded", out.error
    first = out.outputs["jira"]
    res = await ctx.gateway.invoke("jira_backlog", "create_epics", {}, ctx.tool_context("jira"))
    assert res.get("idempotent_replay") is True and res["data"]["created"] == first["data"]["created"]


def test_export_runtime_native():
    exp = get_adapter().export(template_graph("RFP_SOW"))
    assert exp["format"] in ("mermaid", "autogen-component", "n8n-workflow") and exp["content"]
