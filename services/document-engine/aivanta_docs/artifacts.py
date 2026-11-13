"""Map typed agent artifacts to renderable documents."""
from __future__ import annotations

import json
from typing import Any


def _src_list(items) -> list[str]:
    out = []
    for s in items or []:
        if isinstance(s, dict):
            out.append(f"{s.get('document', '')} — {s.get('locator', '')}")
        else:
            out.append(str(s))
    return sorted(set(out))


def _maybe_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def structured_sections_from_agent_output(raw: Any, heading: str = "Agent output") -> list[dict[str, Any]]:
    """Turn agent JSON payloads into human document sections (tables / bullets / prose)."""
    data = _maybe_json(raw)
    if not isinstance(data, dict):
        return [{"heading": heading, "body": str(raw)}]

    sections: list[dict[str, Any]] = []

    if "requirements" in data:
        rows = [["ID", "Requirement", "Type", "Priority", "Category", "Source", "Confidence"]]
        for r in data.get("requirements") or []:
            src = r.get("source") or {}
            loc = f"{src.get('document', '')} {src.get('locator', '')}".strip()
            conf = r.get("confidence")
            conf_s = f"{conf:.0%}" if isinstance(conf, (int, float)) else str(conf or "")
            rows.append([r.get("id", ""), r.get("text", ""), r.get("type", ""), r.get("priority", ""),
                         r.get("category", ""), loc, conf_s])
        sections.append({"heading": "Requirements", "table": rows})
        if data.get("constraints"):
            sections.append({"heading": "Constraints", "bullets": list(data["constraints"])})
        if data.get("evaluation_criteria"):
            sections.append({"heading": "Evaluation criteria", "bullets": list(data["evaluation_criteria"])})
        if data.get("clarifications"):
            sections.append({"heading": "Clarifications", "bullets": list(data["clarifications"])})
        if data.get("deadlines"):
            sections.append({"heading": "Deadlines", "bullets": list(data["deadlines"])})
        return sections

    if "sections" in data and ("title" in data or "objective" in data):
        sec_list = list(data.get("sections") or [])
        # Keep upstream lineage first when present.
        for sec in sec_list:
            if (sec.get("heading") or "") == "Inputs from prior agents":
                sections.append({"heading": "Inputs from prior agents", "body": sec.get("body", ""), "bullets": sec.get("bullets") or []})
        if data.get("objective"):
            sections.append({"heading": "Business objective", "body": data["objective"]})
        for sec in sec_list:
            if (sec.get("heading") or "") == "Inputs from prior agents":
                continue
            sections.append({"heading": sec.get("heading") or "Section", "body": sec.get("body", ""), "bullets": sec.get("bullets") or []})
        if data.get("traceability"):
            sections.append({"heading": "Traceability", "table": [["Requirement", "BRD section"]] + [[k, v] for k, v in data["traceability"].items()]})
        return sections

    if "scope" in data and "deliverables" in data:
        sections += [
            {"heading": "Scope", "body": data.get("scope", "")},
            {"heading": "Deliverables", "bullets": list(data.get("deliverables") or [])},
            {"heading": "Milestones", "bullets": list(data.get("milestones") or [])},
            {"heading": "Exclusions", "bullets": list(data.get("exclusions") or [])},
            {"heading": "Acceptance", "body": data.get("acceptance", "")},
        ]
        return sections

    if "recommended" in data and "options" in data:
        sections.append({"heading": "Recommendation", "body": data.get("recommended", "")})
        sections.append({"heading": "Options", "table": [["Option", "Summary", "Scores"]] + [
            [o.get("name", ""), o.get("summary", ""), ", ".join(f"{k} {v}" for k, v in (o.get("scores") or {}).items())]
            for o in data.get("options") or []
        ]})
        if data.get("integrations"):
            sections.append({"heading": "Integrations", "bullets": list(data["integrations"])})
        if data.get("adr"):
            sections.append({"heading": "ADR", "body": data["adr"]})
        return sections

    if "choices" in data:
        sections.append({"heading": "Technology choices", "table": [["Need", "Open source", "Managed", "Recommendation", "Rationale"]] + [
            [c.get("need", ""), c.get("open_source", ""), c.get("managed", ""), c.get("recommendation", ""), c.get("rationale", "")]
            for c in data.get("choices") or []
        ]})
        return sections

    if "role_lines" in data:
        sections.append({"heading": "Phases", "bullets": list(data.get("phases") or [])})
        sections.append({"heading": "Role lines", "table": [["Role", "FTE", "Months", "Rationale"]] + [
            [ln.get("role", ""), ln.get("fte", ""), ln.get("months", ""), ln.get("rationale", "")]
            for ln in data.get("role_lines") or []
        ]})
        if data.get("assumptions"):
            sections.append({"heading": "Assumptions", "bullets": list(data["assumptions"])})
        return sections

    if "assignments" in data:
        sections.append({"heading": "Assignments", "table": [["Role", "Person", "Allocation %", "Verified"]] + [
            [a.get("role", ""), a.get("person", ""), a.get("allocation_pct", ""), "Yes" if a.get("verified") else "No"]
            for a in data.get("assignments") or []
        ]})
        if data.get("gaps"):
            sections.append({"heading": "Gaps", "bullets": list(data["gaps"])})
        return sections

    if "findings" in data:
        sections.append({"heading": "Findings", "bullets": [
            f"[{f.get('severity', 'info')}] {f.get('message', '')}" for f in data.get("findings") or []
        ]})
        if data.get("recommendation"):
            sections.append({"heading": "Recommendation", "body": str(data["recommendation"])})
        return sections

    # Generic structured fallback: avoid dumping opaque JSON blobs as the body.
    for key, value in data.items():
        label = str(key).replace("_", " ").title()
        if isinstance(value, list) and value and all(isinstance(x, str) for x in value):
            sections.append({"heading": label, "bullets": value})
        elif isinstance(value, dict):
            sections.append({"heading": label, "table": [["Field", "Value"]] + [[str(k), str(v)] for k, v in value.items()]})
        elif isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
            cols = sorted({k for row in value for k in row.keys()})
            sections.append({"heading": label, "table": [cols] + [[str(row.get(c, "")) for c in cols] for row in value]})
        else:
            sections.append({"heading": label, "body": str(value)})
    return sections or [{"heading": heading, "body": json.dumps(data, indent=2)}]


def format_agent_output_text(raw: Any) -> str:
    """Plain-text structured preview for the inspector (not raw JSON)."""
    sections = structured_sections_from_agent_output(raw)
    lines: list[str] = []
    for sec in sections:
        lines.append(sec.get("heading") or "Section")
        lines.append("=" * len(lines[-1]))
        if sec.get("body"):
            lines.append(str(sec["body"]))
        for b in sec.get("bullets") or []:
            lines.append(f"• {b}")
        table = sec.get("table") or []
        if table:
            header, *rows = table
            lines.append(" | ".join(str(c) for c in header))
            lines.append("-|-".join("-" * max(3, len(str(c))) for c in header))
            for row in rows:
                lines.append(" | ".join(str(c) for c in row))
        lines.append("")
    return "\n".join(lines).strip()


def artifact_to_document(artifact: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    """artifact: {type, version, content, approval_state, run_id, graph_version, source_ids}"""
    c = artifact.get("content") or {}
    kind = artifact.get("type")
    doc: dict[str, Any] = {
        "title": f"{kind} — {project.get('name', '')}",
        "type": kind, "version": artifact.get("version", 1), "review_status": artifact.get("approval_state", "draft"),
        "project_code": project.get("code"), "client": project.get("client"), "run_id": artifact.get("run_id"),
        "graph_version": artifact.get("graph_version"), "sections": [], "assumptions": [], "sources": list(artifact.get("source_ids") or []),
    }
    S = doc["sections"]
    if kind == "Compliance matrix":
        rows = [["ID", "Requirement", "Type", "Priority", "Source", "Confidence"]]
        srcs = []
        for r in c.get("requirements", []):
            rows.append([r["id"], r["text"], r["type"], r["priority"], f"{r['source']['document']} {r['source']['locator']}", f"{r['confidence']:.0%}"])
            srcs.append(r["source"])
        S.append({"heading": "Compliance matrix", "table": rows})
        if c.get("clarifications"):
            S.append({"heading": "Clarifications", "bullets": c["clarifications"]})
        doc["assumptions"] = c.get("constraints", [])
        doc["sources"] += _src_list(srcs)
    elif kind == "BRD":
        doc["title"] = c.get("title", doc["title"])
        S.append({"heading": "Business objective", "body": c.get("objective", "")})
        for sec in c.get("sections", []):
            S.append({"heading": sec["heading"], "body": sec.get("body", ""), "bullets": sec.get("bullets", [])})
            doc["sources"] += _src_list(sec.get("sources"))
        if c.get("traceability"):
            S.append({"heading": "Traceability", "table": [["Requirement", "BRD section"]] + [[k, v] for k, v in c["traceability"].items()]})
    elif kind == "SOW":
        doc["title"] = c.get("title", doc["title"])
        S += [{"heading": "Scope", "body": c.get("scope", "")}, {"heading": "Deliverables", "bullets": c.get("deliverables", [])},
              {"heading": "Milestones", "bullets": c.get("milestones", [])}, {"heading": "Exclusions", "bullets": c.get("exclusions", [])},
              {"heading": "Acceptance", "body": c.get("acceptance", "")}]
        doc["assumptions"] = c.get("assumptions", [])
        doc["sources"] += _src_list(c.get("sources"))
    elif kind == "Architecture proposal":
        S.append({"heading": "Recommendation", "body": c.get("recommended", "")})
        S.append({"heading": "Options", "table": [["Option", "Summary", "Scores"]] + [[o["name"], o["summary"], ", ".join(f"{k} {v}" for k, v in o.get("scores", {}).items())] for o in c.get("options", [])]})
        S.append({"heading": "Integrations", "bullets": c.get("integrations", [])})
        S.append({"heading": "ADR", "body": c.get("adr", "")})
    elif kind == "Pricing worksheet":
        res = c.get("result", {})
        S.append({"heading": "Role lines", "table": [["Role", "FTE", "Months", "Person-months", "Monthly rate", "Cost"]] +
                  [[ln["role"], ln["fte"], ln["months"], ln["person_months"], ln["monthly_rate"], ln["cost"]] for ln in res.get("lines", [])]})
        S.append({"heading": "Totals", "table": [["Line", "Amount"]] + [[k, res.get(k, "")] for k in
                  ("labor", "cloud", "licenses", "travel", "overhead", "contingency", "delivery_cost", "list_price", "selling_price", "effective_margin_pct")]})
        S.append({"heading": "Flags", "bullets": [f["message"] for f in c.get("flags", [])] or ["No flags"]})
        doc["assumptions"] = [f"Rate card {res.get('rate_card_version', '')}", f"FX {res.get('fx_version', '')}", f"Currency {res.get('currency', '')}", "Taxes excluded"]
    elif kind in ("agent_output", "portal_pack"):
        doc["title"] = c.get("title") or doc["title"]
        if c.get("role"):
            S.append({"heading": "Role", "body": c["role"]})
        stored = c.get("sections") or []
        has_chain_section = any(isinstance(s, dict) and s.get("heading") == "Inputs from prior agents" for s in stored)
        if c.get("inputs_from") and not has_chain_section:
            S.append({
                "heading": "Inputs from prior agents",
                "bullets": [
                    (
                        f"{i.get('name', 'Agent')} ({i.get('template', '')})"
                        + (f" — {i.get('summary')}" if i.get("summary") else "")
                        + (" · auto-simulated" if i.get("simulated") else "")
                    )
                    for i in (c.get("inputs_from") or [])
                    if isinstance(i, dict)
                ],
            })
        raw = c.get("raw")
        structured = structured_sections_from_agent_output(raw, heading=c.get("agent") or "Agent output") if raw is not None else []
        # Prefer stored sections when they already include chain metadata; else derive from raw.
        if has_chain_section:
            for sec in stored:
                S.append({
                    "heading": sec.get("heading") or "Section",
                    "body": sec.get("body", ""),
                    "bullets": sec.get("bullets") or [],
                    "table": sec.get("table"),
                })
        elif structured:
            S.extend(structured)
        else:
            for sec in stored:
                body = sec.get("body", "")
                parsed = _maybe_json(body)
                if isinstance(parsed, dict):
                    S.extend(structured_sections_from_agent_output(parsed, heading=sec.get("heading") or "Section"))
                else:
                    S.append({"heading": sec.get("heading") or "Section", "body": body, "bullets": sec.get("bullets") or [], "table": sec.get("table")})
        if c.get("assumptions"):
            doc["assumptions"] = list(c["assumptions"])
    else:
        S.append({"heading": "Content", "body": str(c)})
    return doc
