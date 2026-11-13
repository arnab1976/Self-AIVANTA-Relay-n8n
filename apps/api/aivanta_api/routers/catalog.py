"""Agent library and Tool / MCP registry."""
from __future__ import annotations

from aivanta_connectors import load_registry
from aivanta_templates import get_template, load_templates
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import AgentDefinition, CanvasGraphRow, ToolPolicy
from ..security import Principal, current_principal, require
from ..services.common import approved_tools

router = APIRouter(tags=["catalog"])


class AgentVersionIn(BaseModel):
    instructions: str
    model_profile: str | None = None


class ToolPatch(BaseModel):
    approved: bool


@router.get("/agents")
def list_agents(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    defs = {}
    for d in db.scalars(select(AgentDefinition).where(AgentDefinition.tenant_id == p.tenant_id).order_by(AgentDefinition.version)):
        defs[d.template_id] = d
    graphs = db.scalars(select(CanvasGraphRow).where(CanvasGraphRow.tenant_id == p.tenant_id, CanvasGraphRow.archived.is_(False))).all()
    out = []
    for t in load_templates().values():
        d = defs.get(t.id)
        used = sum(1 for g in graphs if any(n.get("config", {}).get("template") == t.id for n in g.draft.get("nodes", [])))
        out.append(t.model_dump() | {"tenant_version": d.version if d else t.version, "tenant_instructions": d.instructions if d else t.instructions,
                                     "used_in_canvases": used})
    return out


@router.post("/agents/{template_id}/versions", status_code=201)
def new_agent_version(template_id: str, body: AgentVersionIn, p: Principal = Depends(require("agent:edit")), db: Session = Depends(get_db)):
    try:
        tpl = get_template(template_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    if len(body.instructions) > 4000:
        raise HTTPException(422, "Instructions must stay under 4,000 characters (bounded prompts).")
    current = db.scalar(select(func.max(AgentDefinition.version)).where(AgentDefinition.tenant_id == p.tenant_id, AgentDefinition.template_id == template_id))
    v = (current or tpl.version) + 1
    d = AgentDefinition(tenant_id=p.tenant_id, template_id=template_id, version=v, instructions=body.instructions,
                        model_profile=body.model_profile or tpl.default_model, tools=tpl.tools, policies=["cite_sources", "json_schema", "pii_redaction"],
                        created_by=p.name)
    db.add(d)
    audit.record(db, p.tenant_id, p.name, p.role, "Agent definition versioned", f"{template_id} v{v}")
    db.commit()
    return {"template_id": template_id, "version": v}


@router.get("/tools")
def list_tools(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    appr = approved_tools(db, p.tenant_id)
    return [{"id": t.id, "kind": t.kind, "description": t.description, "endpoint": t.endpoint, "scopes": list(t.scopes),
             "credential_ref": t.credential_ref, "timeout_s": t.timeout_s, "external": t.external, "approved": appr.get(t.id, False)}
            for t in load_registry().values()]


@router.patch("/tools/{tool_id}")
def patch_tool(tool_id: str, body: ToolPatch, p: Principal = Depends(require("tool:approve")), db: Session = Depends(get_db)):
    if tool_id not in load_registry():
        raise HTTPException(404, "Unknown tool")
    row = db.scalars(select(ToolPolicy).where(ToolPolicy.tenant_id == p.tenant_id, ToolPolicy.tool_id == tool_id)).first()
    if not row:
        row = ToolPolicy(tenant_id=p.tenant_id, tool_id=tool_id)
        db.add(row)
    row.approved = body.approved
    audit.record(db, p.tenant_id, p.name, p.role, f"Tool {'approved' if body.approved else 'revoked'}", tool_id)
    db.commit()
    return {"id": tool_id, "approved": body.approved}


@router.get("/tools/{tool_id}/schema")
def tool_schema(tool_id: str, p: Principal = Depends(current_principal)):
    reg = load_registry()
    if tool_id not in reg:
        raise HTTPException(404, "Unknown tool")
    t = reg[tool_id]
    return {"tool": t.id, "endpoint": t.endpoint, "auth": {"type": "oauth2", "scopes": list(t.scopes), "credential_ref": t.credential_ref},
            "execution_policy": {"timeout_s": t.timeout_s, "requires_upstream_approval": t.external, "egress": "allowlist"},
            "input_schema": t.input_schema, "output_schema": t.output_schema}
