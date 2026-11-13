"""Workflow template library: RFP-to-SOW, RFP-to-BRD, Estimate-to-Proposal,
Cloud Cost Review and Resource Deployment (blueprint section 6)."""
from __future__ import annotations

from typing import Any

from .models import CanvasGraph, Edge, Node, Position

AGENT_DEFAULTS: dict[str, dict[str, Any]] = {
    "RFP_INTELLIGENCE": {"input_schema": "rfp.v1", "output_schema": "requirements.v1", "tools": ["document_reader"], "model_profile": "enterprise-reasoning"},
    "BRD_AUTHOR": {"input_schema": "requirements.v1", "output_schema": "brd.v1", "tools": [], "model_profile": "enterprise-reasoning"},
    "SOW_AUTHOR": {"input_schema": "brd.v1", "output_schema": "sow.v1", "tools": [], "model_profile": "enterprise-reasoning"},
    "SOLUTION_ARCHITECT": {"input_schema": "requirements.v1", "output_schema": "architecture.v1", "tools": ["sharepoint_search"], "model_profile": "enterprise-reasoning"},
    "TECH_ADVISOR": {"input_schema": "architecture.v1", "output_schema": "tech_matrix.v1", "tools": ["cloud_pricing"], "model_profile": "enterprise-fast"},
    "EFFORT_ESTIMATOR": {"input_schema": "tech_matrix.v1", "output_schema": "effort.v1", "tools": [], "model_profile": "enterprise-reasoning"},
    "CLOUD_FINOPS": {"input_schema": "tech_matrix.v1", "output_schema": "cloud_cost.v1", "tools": ["cloud_pricing"], "model_profile": "enterprise-fast"},
    "COMMERCIAL_PRICING": {"input_schema": "effort.v1", "output_schema": "pricing.v1", "tools": [], "model_profile": "enterprise-fast"},
    "RESOURCE_PLANNER": {"input_schema": "effort.v1", "output_schema": "staffing.v1", "tools": ["hrms_availability"], "model_profile": "enterprise-fast"},
    "GOVERNANCE_REVIEWER": {"input_schema": "package.v1", "output_schema": "review.v1", "tools": [], "model_profile": "enterprise-reasoning"},
}

TOOL_CREDENTIALS = {
    "document_reader": "vault://docs/reader", "ocr_parser": "vault://docs/ocr", "object_store": "vault://store/ro",
    "template_renderer": "vault://docs/render", "sharepoint_search": "vault://m365/sites", "crm_opportunity": "vault://crm/ro",
    "hrms_availability": "vault://hrms/ro", "jira_backlog": "vault://atlassian/jira", "cloud_pricing": "vault://pricing/ro",
    "email_send": "vault://m365/mail",
}


def default_config(node_type: str, **overrides: Any) -> dict[str, Any]:
    if node_type == "agent":
        tpl = overrides.get("template", "RFP_INTELLIGENCE")
        base = {"template": tpl, "role": "", "description": "",
                "temperature": 0.2, "frequency_penalty": 0.0, "presence_penalty": 0.0,
                "mcp_tools": [], "retry": 2, "timeout_s": 180,
                "guardrails": ["cite_sources", "json_schema", "pii_redaction", "injection_filter"],
                "team_pattern": "single", "fail_simulation": False, **AGENT_DEFAULTS.get(tpl, {})}
        base["tools"] = list(base.get("tools", []))
        if not base.get("mcp_tools"):
            base["mcp_tools"] = list(base["tools"])
    elif node_type == "tool":
        tid = overrides.get("tool_id", "document_reader")
        base = {"tool_id": tid, "operation": "read", "timeout_s": 60, "retry": 1,
                "credential_ref": TOOL_CREDENTIALS.get(tid, "vault://unset"), "fail_simulation": False}
    elif node_type == "decision":
        base = {"rule": "open_clarifications > 0", "sim_outcome": "auto"}
    elif node_type == "approval":
        base = {"approver_role": "finance", "sla_hours": 24, "evidence": "Linked artifacts"}
    elif node_type == "data":
        base = {"knowledge_base": "approved-proposals", "retrieval": "hybrid", "access_filter": "tenant+project", "top_k": 6}
    elif node_type == "calc":
        base = {"formula": "selling_price", "rate_card_version": "tenant:current", "currency_rule": "tenant", "tax_rule": "excluded"}
    elif node_type == "start":
        base = {"input_schema": "project.v1"}
    else:
        base = {"output_schema": "proposal_package.v1"}
    base.update(overrides)
    return base


def _pos(c: int, r: int) -> Position:
    return Position(x=40 + c * 240, y=40 + r * 120)


def _build(nodes: list[tuple], edges: list[tuple]) -> CanvasGraph:
    out_nodes = []
    for spec in nodes:
        nid, ntype, name, c, r, *rest = spec
        cfg = rest[0] if rest else {}
        out_nodes.append(Node(id=nid, type=ntype, name=name, position=_pos(c, r), config=default_config(ntype, **cfg)))
    out_edges = [Edge(id=f"e{i + 1}", source=s, target=t, label=(lab[0] if lab else None)) for i, (s, t, *lab) in enumerate(edges)]
    return CanvasGraph(nodes=out_nodes, edges=out_edges)


def rfp_to_sow() -> CanvasGraph:
    return _build(
        [
            ("start", "start", "Start", 0, 1),
            ("upload", "tool", "RFP Upload", 1, 1, {"tool_id": "object_store", "operation": "get_rfp"}),
            ("ocr", "tool", "Parse / OCR", 2, 1, {"tool_id": "ocr_parser", "operation": "parse", "timeout_s": 180}),
            ("rfp", "agent", "RFP Intelligence", 3, 1, {"template": "RFP_INTELLIGENCE"}),
            ("gap", "decision", "Requirement Gap?", 4, 1),
            ("clar", "approval", "Clarification Approval", 5, 0, {"approver_role": "presales", "evidence": "Clarification log"}),
            ("kb", "data", "Prior Proposals KB", 5, 2),
            ("brd", "agent", "BRD Author", 6, 0, {"template": "BRD_AUTHOR"}),
            ("arch", "agent", "Solution Architect", 6, 2, {"template": "SOLUTION_ARCHITECT"}),
            ("tech", "agent", "Technology Advisor", 7, 1, {"template": "TECH_ADVISOR"}),
            ("est", "agent", "Effort Estimator", 8, 0, {"template": "EFFORT_ESTIMATOR"}),
            ("fin", "agent", "Cloud FinOps", 8, 2, {"template": "CLOUD_FINOPS"}),
            ("price", "calc", "Commercial Pricing", 9, 0),
            ("res", "agent", "Resource Planner", 9, 2, {"template": "RESOURCE_PLANNER"}),
            ("gov", "agent", "Governance Reviewer", 10, 1, {"template": "GOVERNANCE_REVIEWER"}),
            ("capp", "approval", "Commercial Approval", 11, 1, {"approver_role": "finance", "evidence": "Pricing worksheet"}),
            ("sow", "agent", "SOW Author", 12, 1, {"template": "SOW_AUTHOR", "team_pattern": "author_reviewer"}),
            ("final", "approval", "Final Review", 13, 1, {"approver_role": "reviewer", "evidence": "SOW and review findings"}),
            ("export", "tool", "Export DOCX/PDF", 14, 1, {"tool_id": "template_renderer", "operation": "render", "timeout_s": 120}),
            ("end", "end", "End", 15, 1),
        ],
        [
            ("start", "upload"), ("upload", "ocr"), ("ocr", "rfp"), ("rfp", "gap"),
            ("gap", "clar", "gaps found"), ("gap", "brd", "no gaps"), ("gap", "arch", "no gaps"),
            ("clar", "brd"), ("clar", "arch"), ("kb", "arch"), ("brd", "tech"), ("arch", "tech"),
            ("tech", "est"), ("tech", "fin"), ("est", "price"), ("fin", "price"), ("est", "res"),
            ("price", "gov"), ("res", "gov"), ("gov", "capp"), ("capp", "sow"), ("sow", "final"),
            ("final", "export"), ("export", "end"),
        ],
    )


def rfp_to_brd() -> CanvasGraph:
    return _build(
        [
            ("start", "start", "Start", 0, 1),
            ("upload", "tool", "RFP Upload", 1, 1, {"tool_id": "object_store", "operation": "get_rfp"}),
            ("ocr", "tool", "Parse / OCR", 2, 1, {"tool_id": "ocr_parser", "operation": "parse"}),
            ("rfp", "agent", "RFP Intelligence", 3, 1, {"template": "RFP_INTELLIGENCE"}),
            ("gap", "decision", "Requirement Gap?", 4, 1),
            ("clar", "approval", "Clarification Approval", 5, 0, {"approver_role": "presales", "evidence": "Clarification log"}),
            ("brd", "agent", "BRD Author", 6, 1, {"template": "BRD_AUTHOR"}),
            ("gov", "agent", "Governance Reviewer", 7, 1, {"template": "GOVERNANCE_REVIEWER"}),
            ("bapp", "approval", "BRD Sign-off", 8, 1, {"approver_role": "reviewer", "evidence": "BRD and traceability"}),
            ("export", "tool", "Export DOCX", 9, 1, {"tool_id": "template_renderer", "operation": "render"}),
            ("end", "end", "End", 10, 1),
        ],
        [("start", "upload"), ("upload", "ocr"), ("ocr", "rfp"), ("rfp", "gap"), ("gap", "clar", "gaps found"),
         ("gap", "brd", "no gaps"), ("clar", "brd"), ("brd", "gov"), ("gov", "bapp"), ("bapp", "export"), ("export", "end")],
    )


def estimate_to_proposal() -> CanvasGraph:
    return _build(
        [
            ("start", "start", "Start", 0, 1),
            ("brdd", "data", "Approved BRD", 0, 0, {"knowledge_base": "project-artifacts"}),
            ("est", "agent", "Effort Estimator", 1, 1, {"template": "EFFORT_ESTIMATOR"}),
            ("fin", "agent", "Cloud FinOps", 2, 2, {"template": "CLOUD_FINOPS"}),
            ("price", "calc", "Commercial Pricing", 3, 1),
            ("res", "agent", "Resource Planner", 3, 0, {"template": "RESOURCE_PLANNER"}),
            ("gov", "agent", "Governance Reviewer", 4, 1, {"template": "GOVERNANCE_REVIEWER"}),
            ("capp", "approval", "Commercial Approval", 5, 1, {"approver_role": "finance", "evidence": "Pricing worksheet"}),
            ("sow", "agent", "SOW Author", 6, 1, {"template": "SOW_AUTHOR"}),
            ("export", "tool", "Export Proposal", 7, 1, {"tool_id": "template_renderer", "operation": "render"}),
            ("end", "end", "End", 8, 1),
        ],
        [("start", "est"), ("brdd", "est"), ("est", "fin"), ("est", "price"), ("fin", "price"), ("est", "res"),
         ("price", "gov"), ("res", "gov"), ("gov", "capp"), ("capp", "sow"), ("sow", "export"), ("export", "end")],
    )


def cloud_cost_review() -> CanvasGraph:
    return _build(
        [
            ("start", "start", "Start", 0, 1),
            ("archd", "data", "Architecture Proposal", 0, 0, {"knowledge_base": "project-artifacts"}),
            ("tech", "agent", "Technology Advisor", 1, 1, {"template": "TECH_ADVISOR"}),
            ("fin", "agent", "Cloud FinOps", 2, 1, {"template": "CLOUD_FINOPS"}),
            ("calc", "calc", "Cloud Cost Scenarios", 3, 1, {"formula": "cloud_scenarios"}),
            ("fapp", "approval", "FinOps Approval", 4, 1, {"approver_role": "finance", "evidence": "Cost scenarios and price snapshot"}),
            ("end", "end", "End", 5, 1),
        ],
        [("start", "tech"), ("archd", "tech"), ("tech", "fin"), ("fin", "calc"), ("calc", "fapp"), ("fapp", "end")],
    )


def resource_deployment() -> CanvasGraph:
    return _build(
        [
            ("start", "start", "Start", 0, 1),
            ("effd", "data", "Effort Plan", 0, 0, {"knowledge_base": "project-artifacts"}),
            ("hrms", "tool", "HRMS Availability", 1, 1, {"tool_id": "hrms_availability", "operation": "query"}),
            ("res", "agent", "Resource Planner", 2, 1, {"template": "RESOURCE_PLANNER"}),
            ("sapp", "approval", "Staffing Commitment", 3, 1, {"approver_role": "pmo", "evidence": "Staffing plan"}),
            ("jira", "tool", "Create Jira Backlog", 4, 1, {"tool_id": "jira_backlog", "operation": "create_epics"}),
            ("end", "end", "End", 5, 1),
        ],
        [("start", "hrms"), ("effd", "res"), ("hrms", "res"), ("res", "sapp"), ("sapp", "jira"), ("jira", "end")],
    )


def blank() -> CanvasGraph:
    return _build([("start", "start", "Start", 0, 1), ("end", "end", "End", 3, 1)], [])


TEMPLATES = {
    "RFP_SOW": ("RFP-to-SOW", "RFP upload to exported SOW with clarification, commercial and final approvals.", rfp_to_sow),
    "RFP_BRD": ("RFP-to-BRD", "Extract requirements, resolve gaps and publish a signed-off BRD.", rfp_to_brd),
    "EST_PROP": ("Estimate-to-Proposal", "From an approved BRD to effort, cloud cost, pricing, staffing and a proposal.", estimate_to_proposal),
    "CLOUD_REVIEW": ("Cloud Cost Review", "Compare providers for a proposed architecture and get FinOps sign-off.", cloud_cost_review),
    "RES_DEPLOY": ("Resource Deployment", "Match effort to HRMS availability, commit staff and create the Jira backlog.", resource_deployment),
    "BLANK": ("Blank canvas", "Start and End only.", blank),
}


def template_graph(key: str) -> CanvasGraph:
    return TEMPLATES[key][2]()
