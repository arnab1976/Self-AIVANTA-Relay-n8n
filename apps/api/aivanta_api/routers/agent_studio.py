"""Interactive agent studio: identity synthesis, single-agent run, portal publish."""
from __future__ import annotations

from typing import Any

from aivanta_docs import format_agent_output_text, structured_sections_from_agent_output
from aivanta_graph import CanvasGraph
from aivanta_templates import get_template, mock_output
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Artifact, Project
from ..security import Principal, current_principal, require
from ..services.common import project_dict, scoped_get

router = APIRouter(prefix="/agent-studio", tags=["agent-studio"])

MCP_TOOL_IDS = [
    "document_reader", "ocr_parser", "object_store", "template_renderer",
    "sharepoint_search", "crm_opportunity", "hrms_availability", "jira_backlog",
    "cloud_pricing", "email_send",
]
GUARDRAIL_OPTIONS = [
    "cite_sources", "json_schema", "pii_redaction", "injection_filter",
    "no_external_send", "human_review_required", "bounded_context", "tool_allowlist_only",
]


class AgentNodeIn(BaseModel):
    graph_id: str
    node_id: str
    project_id: str | None = None
    draft: dict[str, Any] | None = None


class SynthesizeIn(AgentNodeIn):
    """Which identity fields to regenerate. Defaults to description + instructions."""
    fields: list[str] = Field(default_factory=lambda: ["description", "instructions"])


class PublishIn(BaseModel):
    project_id: str
    mode: str = Field(description="single | append")
    agent_name: str
    title: str
    body: str
    node_id: str | None = None
    graph_id: str | None = None


SYNTH_FIELDS = ("description", "instructions")


def _synthesize_fields(node_name: str, cfg: dict, meta: dict, fields: list[str]) -> dict[str, str]:
    role = (cfg.get("role") or meta.get("role") or node_name).strip()
    existing_desc = (cfg.get("description") or "").strip()
    tpl_desc = (meta.get("description") or "").strip()
    out: dict[str, str] = {}

    if "description" in fields:
        seed = existing_desc or role or tpl_desc
        out["description"] = (
            f"{seed.rstrip('.')}. "
            f"Operate as {node_name} for this intake: clarify scope, capture constraints, "
            f"and produce {meta.get('name', node_name)}-ready structured output with source evidence."
        )[:600]

    desc_for_rest = out.get("description") or existing_desc or tpl_desc or role
    if "instructions" in fields:
        focus = desc_for_rest or role or node_name
        out["instructions"] = (
            f"You are {node_name}. Primary objective: {focus.rstrip('.')}.\n"
            f"Role focus: {role or meta.get('role') or 'follow the agent template'}.\n"
            "Stay within the bounded prompt: use only approved MCP tools, cite sources, "
            "do not invent commercial numbers, and return schema-valid JSON for the configured output."
        )[:4000]

    return out


def _node_from_draft(draft: dict, node_id: str) -> dict:
    graph = CanvasGraph.model_validate(draft)
    node = next((n for n in graph.nodes if n.id == node_id), None)
    if not node or node.type != "agent":
        raise HTTPException(404, "Agent node not found in draft")
    return {"node": node, "graph": graph}


def _agent_predecessors(graph: CanvasGraph, node_id: str) -> list:
    """Agents that feed this node, in run order (furthest upstream first)."""
    by_id = {n.id: n for n in graph.nodes}
    incoming: dict[str, list[str]] = {n.id: [] for n in graph.nodes}
    for e in graph.edges:
        incoming.setdefault(e.target, []).append(e.source)

    ordered: list = []
    seen: set[str] = set()

    def walk(nid: str) -> None:
        for src in incoming.get(nid, []):
            if src in seen:
                continue
            seen.add(src)
            walk(src)
            n = by_id.get(src)
            if n and n.type == "agent" and n.id != node_id:
                ordered.append(n)

    walk(node_id)
    return ordered


def _artifact_payload(content: dict | None) -> dict | None:
    if not isinstance(content, dict):
        return None
    raw = content.get("raw")
    if isinstance(raw, dict) and any(k in raw for k in ("requirements", "sections", "title", "recommended", "choices", "role_lines", "findings", "assignments", "workload", "scope")):
        return raw
    if isinstance(raw, dict) and "text" in raw and len(raw) == 1:
        return None
    return raw if isinstance(raw, dict) else None


def _latest_node_artifact(db: Session, tenant_id: str, project_id: str, node_id: str):
    rows = db.scalars(
        select(Artifact)
        .where(
            Artifact.tenant_id == tenant_id,
            Artifact.project_id == project_id,
            Artifact.type == "agent_output",
        )
        .order_by(Artifact.version.desc())
    ).all()
    for art in rows:
        if node_id in (art.source_ids or []):
            return art
        if (art.content or {}).get("node_id") == node_id:
            return art
    return None


def _persist_agent_artifact(
    db: Session,
    *,
    tenant_id: str,
    project_id: str,
    created_by: str,
    node,
    template_id: str,
    cfg: dict,
    output: dict,
    structured_sections: list,
    chain_note: str | None = None,
    title: str | None = None,
    inputs_from: list | None = None,
) -> Artifact:
    text = format_agent_output_text(output) if isinstance(output, dict) else str(output)
    content = {
        "title": title or node.name,
        "agent": node.name,
        "template": template_id,
        "role": cfg.get("role"),
        "node_id": node.id,
        "sections": structured_sections,
        "raw": output if isinstance(output, dict) else {"text": text},
        "assumptions": list((output or {}).get("constraints") or (output or {}).get("assumptions") or []) if isinstance(output, dict) else [],
        "chain_note": chain_note,
        "inputs_from": inputs_from or [],
    }
    latest = db.scalar(
        select(func.max(Artifact.version)).where(Artifact.project_id == project_id, Artifact.type == "agent_output")
    ) or 0
    art = Artifact(
        tenant_id=tenant_id,
        project_id=project_id,
        run_id=None,
        graph_version="agent-studio",
        type="agent_output",
        version=latest + 1,
        content=content,
        source_ids=[node.id],
        reviewer_role="architect",
        approval_state="in_review",
        storage_uri=f"studio/{project_id}/agent_output/v{latest + 1}",
        created_by=created_by,
    )
    db.add(art)
    db.flush()
    return art


def _build_upstream(
    db: Session,
    *,
    principal: Principal,
    proj: Project | None,
    graph: CanvasGraph,
    node_id: str,
    base_ctx: dict,
) -> tuple[dict, list[dict]]:
    """Load or simulate predecessor agent outputs so the current agent can enrich them."""
    upstream: dict[str, Any] = {}
    lineage: list[dict] = []
    if not proj:
        return upstream, lineage

    for pred in _agent_predecessors(graph, node_id):
        pcfg = dict(pred.config or {})
        ptpl = str(pcfg.get("template") or "RFP_INTELLIGENCE")
        art = _latest_node_artifact(db, principal.tenant_id, proj.id, pred.id)
        payload = _artifact_payload(art.content if art else None)
        simulated = False
        if not payload:
            simulated = True
            pred_ctx = {
                **base_ctx,
                "agent": pred.name,
                "role": pcfg.get("role") or base_ctx.get("role"),
                "upstream": dict(upstream),
                "rfp_text": " ".join(filter(None, [
                    pcfg.get("role"),
                    pcfg.get("description"),
                    pcfg.get("instructions"),
                    base_ctx.get("rfp_text"),
                ])),
            }
            payload = mock_output(ptpl, pred_ctx)
            sections = structured_sections_from_agent_output(payload, heading=pred.name)
            art = _persist_agent_artifact(
                db,
                tenant_id=principal.tenant_id,
                project_id=proj.id,
                created_by=principal.name,
                node=pred,
                template_id=ptpl,
                cfg=pcfg,
                output=payload,
                structured_sections=sections,
                chain_note="auto-simulated to feed downstream agent",
            )
        key = ptpl
        # Keep unique keys if two nodes share a template
        if key in upstream:
            key = f"{ptpl}:{pred.id}"
        upstream[key] = payload
        lineage.append({
            "node_id": pred.id,
            "name": pred.name,
            "template": ptpl,
            "artifact_id": art.id if art else None,
            "simulated": simulated,
            "summary": (
                f"{len(payload.get('requirements') or [])} requirements"
                if isinstance(payload, dict) and payload.get("requirements")
                else (payload.get("title") if isinstance(payload, dict) else pred.name)
            ),
        })
    return upstream, lineage


# Default journey when the canvas has no outbound edge yet.
_JOURNEY_NEXT = {
    "RFP_INTELLIGENCE": "BRD_AUTHOR",
    "BRD_AUTHOR": "SOLUTION_ARCHITECT",
    "SOLUTION_ARCHITECT": "TECH_ADVISOR",
    "TECH_ADVISOR": "EFFORT_ESTIMATOR",
    "EFFORT_ESTIMATOR": "CLOUD_FINOPS",
    "CLOUD_FINOPS": "COMMERCIAL_PRICING",
    "COMMERCIAL_PRICING": "RESOURCE_PLANNER",
    "RESOURCE_PLANNER": "GOVERNANCE_REVIEWER",
    "GOVERNANCE_REVIEWER": "SOW_AUTHOR",
    "SOW_AUTHOR": "end",
}


def _pretty_tpl(t: str) -> str:
    return " ".join(w.capitalize() for w in t.lower().split("_"))


def _next_steps(graph: CanvasGraph, node_id: str) -> list[dict]:
    outs = [e for e in graph.edges if e.source == node_id]
    by_id = {n.id: n for n in graph.nodes}
    recs = []
    for e in outs:
        t = by_id.get(e.target)
        if not t:
            continue
        recs.append({
            "node_id": t.id,
            "name": t.name,
            "type": t.type,
            "label": e.label,
            "recommended": t.type in ("agent", "decision", "approval", "tool", "data", "calc"),
            "suggested": False,
        })
    # Prefer agent/decision/approval as the primary recommendation
    recs.sort(key=lambda r: 0 if r["type"] in ("agent", "decision", "approval") else 1)
    if recs:
        recs[0]["recommended"] = True
        for r in recs[1:]:
            r["recommended"] = False
        return recs

    # No outbound edges — suggest the next journey agent (or End).
    node = by_id.get(node_id)
    tpl = (node.config or {}).get("template") if node else None
    nxt = _JOURNEY_NEXT.get(tpl or "", "end")
    if nxt == "end":
        end = next((n for n in graph.nodes if n.type == "end"), None)
        return [{
            "node_id": end.id if end else "",
            "name": end.name if end else "End",
            "type": "end",
            "label": "suggested path",
            "recommended": True,
            "suggested": True,
            "template": None,
        }]
    existing = next(
        (n for n in graph.nodes if n.type == "agent" and (n.config or {}).get("template") == nxt and n.id != node_id),
        None,
    )
    return [{
        "node_id": existing.id if existing else "",
        "name": existing.name if existing else _pretty_tpl(nxt),
        "type": "agent",
        "label": "suggested path",
        "recommended": True,
        "suggested": True,
        "template": nxt,
    }]


def _tpl_meta(template_id: str) -> dict:
    try:
        tpl = get_template(template_id)
        return {
            "role": tpl.role,
            "description": f"Inputs: {tpl.inputs}. Outputs: {tpl.outputs}.",
            "default_model": tpl.default_model,
            "default_tools": list(tpl.tools),
            "name": tpl.name,
        }
    except KeyError:
        return {"role": "", "description": "", "default_model": "enterprise-fast", "default_tools": [], "name": template_id}


@router.get("/options")
def options(p: Principal = Depends(current_principal)):
    return {
        "guardrails": GUARDRAIL_OPTIONS,
        "mcp_tools": MCP_TOOL_IDS,
        "model_profiles": ["enterprise-reasoning", "enterprise-fast", "local-open-weight", "experimental-preview"],
        "llm_defaults": {"temperature": 0.2, "frequency_penalty": 0.0, "presence_penalty": 0.0},
    }


@router.post("/synthesize")
def synthesize_identity(body: SynthesizeIn, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    if not body.draft:
        raise HTTPException(422, "draft is required")
    wanted = [f for f in body.fields if f in SYNTH_FIELDS]
    if not wanted:
        raise HTTPException(422, f"fields must include one of: {', '.join(SYNTH_FIELDS)}")
    packed = _node_from_draft(body.draft, body.node_id)
    node = packed["node"]
    cfg = dict(node.config or {})
    meta = _tpl_meta(str(cfg.get("template", "RFP_INTELLIGENCE")))
    synthesized = _synthesize_fields(node.name, cfg, meta, wanted)
    audit.record(
        db, p.tenant_id, p.name, p.role,
        "Agent identity synthesized",
        f"{node.name} · {', '.join(wanted)} · {body.graph_id}",
    )
    db.commit()
    return {
        **synthesized,
        "role": (cfg.get("role") or meta["role"] or node.name).strip(),
        "model_profile": cfg.get("model_profile") or meta["default_model"],
        "fields": wanted,
    }


@router.post("/tagline")
def synthesize_tagline(body: AgentNodeIn, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    """Backward-compatible alias for Synthesize all (description + instructions)."""
    return synthesize_identity(
        SynthesizeIn(
            graph_id=body.graph_id,
            node_id=body.node_id,
            project_id=body.project_id,
            draft=body.draft,
            fields=["description", "instructions"],
        ),
        p, db,
    )


@router.post("/run")
def run_agent(body: AgentNodeIn, p: Principal = Depends(require("graph:edit")), db: Session = Depends(get_db)):
    if not body.draft:
        raise HTTPException(422, "draft is required")
    packed = _node_from_draft(body.draft, body.node_id)
    node, graph = packed["node"], packed["graph"]
    cfg = dict(node.config or {})
    template_id = str(cfg.get("template", "RFP_INTELLIGENCE"))
    meta = _tpl_meta(template_id)
    if not cfg.get("role"):
        cfg["role"] = meta["role"]
    if not cfg.get("description"):
        cfg["description"] = meta["description"]
    cfg.pop("tagline", None)

    proj = scoped_get(db, Project, body.project_id, p) if body.project_id else None
    project_info = project_dict(proj) if proj else {}
    rfp_text = " ".join(filter(None, [
        cfg.get("role"),
        cfg.get("description"),
        cfg.get("instructions"),
        (proj.scope if proj else ""),
        (proj.name if proj else ""),
        (proj.client if proj else ""),
        (proj.industry if proj else ""),
    ]))
    base_ctx = {
        "project_id": body.project_id,
        "tenant_id": p.tenant_id,
        "agent": node.name,
        "role": cfg.get("role"),
        "model_profile": cfg.get("model_profile", meta["default_model"]),
        "temperature": float(cfg.get("temperature", 0.2)),
        "frequency_penalty": float(cfg.get("frequency_penalty", 0.0)),
        "presence_penalty": float(cfg.get("presence_penalty", 0.0)),
        "guardrails": list(cfg.get("guardrails") or []),
        "mcp_tools": list(cfg.get("mcp_tools") or cfg.get("tools") or []),
        "project": project_info,
        "rfp_text": rfp_text,
    }
    upstream, inputs_from = _build_upstream(
        db, principal=p, proj=proj, graph=graph, node_id=body.node_id, base_ctx=base_ctx,
    )
    actx = {**base_ctx, "upstream": upstream}
    try:
        output = mock_output(template_id, actx)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Agent run failed: {exc}") from exc

    structured_sections = structured_sections_from_agent_output(output, heading=node.name)
    chain_bullets = [
        f"{i['name']} ({i['template']})"
        + (f" - {i['summary']}" if i.get("summary") else "")
        + (" [auto-simulated]" if i.get("simulated") else "")
        for i in inputs_from
    ]
    if inputs_from:
        # Replace or insert a single chain section so prior-agent input is visible exactly once.
        replaced = False
        cleaned: list[dict] = []
        for sec in structured_sections:
            if (sec.get("heading") or "") == "Inputs from prior agents":
                if replaced:
                    continue
                cleaned.append({**sec, "bullets": chain_bullets, "body": ""})
                replaced = True
            else:
                cleaned.append(sec)
        if not replaced:
            cleaned.insert(0, {"heading": "Inputs from prior agents", "bullets": chain_bullets, "body": ""})
        structured_sections = cleaned
    # Prefer assembled sections (includes chain metadata) over raw-only formatting.
    if structured_sections:
        lines: list[str] = []
        for sec in structured_sections:
            heading = sec.get("heading") or "Section"
            lines.append(heading)
            lines.append("=" * len(heading))
            if sec.get("body"):
                lines.append(str(sec["body"]))
            for b in sec.get("bullets") or []:
                lines.append(f"- {b}")
            table = sec.get("table") or []
            if table:
                for row in table:
                    lines.append(" | ".join(str(c) for c in row))
            lines.append("")
        text = "\n".join(lines).strip()
    else:
        text = format_agent_output_text(output) if isinstance(output, dict) else str(output)
    next_steps = _next_steps(graph, body.node_id)
    primary = next((n for n in next_steps if n.get("recommended")), next_steps[0] if next_steps else None)

    artifact_id = None
    if proj:
        art = _persist_agent_artifact(
            db,
            tenant_id=p.tenant_id,
            project_id=proj.id,
            created_by=p.name,
            node=node,
            template_id=template_id,
            cfg=cfg,
            output=output,
            structured_sections=structured_sections,
            chain_note=f"consumed {len(inputs_from)} upstream agent(s)" if inputs_from else None,
            title=f"{node.name} — {proj.name}" if proj.name else node.name,
            inputs_from=inputs_from,
        )
        artifact_id = art.id
        audit.record(
            db, p.tenant_id, p.name, p.role, "Agent studio run",
            f"{node.name} · {proj.code} · upstream={len(inputs_from)}",
        )
        db.commit()

    return {
        "node_id": body.node_id,
        "agent": node.name,
        "output": output,
        "output_text": text,
        "artifact_id": artifact_id,
        "inputs_from": inputs_from,
        "next_recommendation": primary,
        "next_steps": next_steps,
        "simulated": True,
        "params": {
            "model_profile": actx["model_profile"],
            "temperature": actx["temperature"],
            "frequency_penalty": actx["frequency_penalty"],
            "presence_penalty": actx["presence_penalty"],
        },
    }


@router.post("/publish")
def publish_to_portal(body: PublishIn, p: Principal = Depends(require("graph:edit")), db: Session = Depends(get_db)):
    if body.mode not in ("single", "append"):
        raise HTTPException(422, "mode must be single or append")
    proj = scoped_get(db, Project, body.project_id, p)
    section = {"heading": body.agent_name, "body": body.body, "node_id": body.node_id, "graph_id": body.graph_id}
    existing = None
    if body.mode == "append":
        existing = db.scalars(
            select(Artifact).where(
                Artifact.tenant_id == p.tenant_id,
                Artifact.project_id == proj.id,
                Artifact.type == "portal_pack",
            ).order_by(Artifact.version.desc())
        ).first()

    if existing and body.mode == "append":
        content = dict(existing.content or {})
        sections = list(content.get("sections") or [])
        sections.append(section)
        content["sections"] = sections
        content["title"] = content.get("title") or body.title or f"{proj.code} portal pack"
        latest = existing.version
        art = Artifact(
            tenant_id=p.tenant_id, project_id=proj.id, run_id=existing.run_id, graph_version=existing.graph_version,
            type="portal_pack", version=latest + 1, content=content,
            source_ids=list(existing.source_ids or []) + ([body.node_id] if body.node_id else []),
            reviewer_role=existing.reviewer_role, approval_state="in_review",
            storage_uri=f"studio/{proj.id}/portal_pack/v{latest + 1}", created_by=p.name,
        )
    else:
        art = Artifact(
            tenant_id=p.tenant_id, project_id=proj.id, run_id=None, graph_version="agent-studio",
            type="portal_pack", version=1,
            content={"title": body.title or f"{proj.code} portal pack", "sections": [section]},
            source_ids=[body.node_id] if body.node_id else [],
            reviewer_role="architect", approval_state="in_review",
            storage_uri=f"studio/{proj.id}/portal_pack/v1", created_by=p.name,
        )
    db.add(art)
    audit.record(db, p.tenant_id, p.name, p.role, "Published agent output to portal", f"{body.agent_name} · {proj.code} · {body.mode}")
    db.commit()
    return {"id": art.id, "type": art.type, "version": art.version, "sections": len(art.content.get("sections") or [])}
