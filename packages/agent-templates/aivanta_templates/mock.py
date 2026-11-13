"""Deterministic mock outputs used when LLM_PROVIDER=mock.

They let the whole platform (both runtimes, the API and the UI) run end to
end without model credentials, and they back the contract tests. Outputs are
schema-valid and derived from the project and upstream artifacts so the run
still behaves like a real one (requirement count drives effort, and so on).
"""
from __future__ import annotations

import re
from typing import Any

from .schemas import output_model

DEFAULT_REQS = {
    "BFSI": [
        ("FR", "Capture digital applications across web, mobile and branch-assisted channels.", "§3.1 p.9"),
        ("FR", "Integrate with the core system of record and credit bureaus in real time.", "§3.4 p.11"),
        ("FR", "Configure approval matrices by product, amount and risk band without code changes.", "§3.6 p.12"),
        ("NFR", "Decision APIs respond within 2 seconds at the 95th percentile.", "§6.1 p.21"),
        ("NFR", "Customer data is encrypted at rest and in transit and hosted in-region.", "§6.3 p.22"),
        ("NFR", "Keep immutable audit trails for every decision for eight years.", "§6.5 p.23"),
    ],
    "Healthcare": [
        ("FR", "Patients book, reschedule and cancel appointments across all clinics.", "§2.1 p.5"),
        ("FR", "Integrate with the EHR using HL7 FHIR R4 APIs.", "§3.3 p.10"),
        ("NFR", "The solution is HIPAA compliant with a BAA for every hosted component.", "§5.2 p.15"),
        ("NFR", "Patient interfaces meet WCAG 2.1 AA.", "§5.4 p.16"),
    ],
    "Insurance": [
        ("FR", "Capture FNOL and policy servicing requests across web, mobile and call centre.", "§2.1 p.6"),
        ("FR", "Integrate with policy admin, claims and CRM systems for a single customer view.", "§3.2 p.10"),
        ("FR", "Support underwriter and operations workbenches with role-based access.", "§3.5 p.12"),
        ("NFR", "Customer and policy data must remain in-region with encryption at rest and in transit.", "§6.1 p.18"),
        ("NFR", "Decision and scoring APIs respond within 2 seconds at the 95th percentile.", "§6.2 p.19"),
    ],
}
RETENTION_REQS = [
    ("FR", "Develop a retention propensity model for Private Car renewals on the online channel.", "§1.1 p.3"),
    ("FR", "Score each renewal case using policy, claims, payment and digital engagement features.", "§2.2 p.7"),
    ("FR", "Provide role-based workspaces for retention analysts, product owners and administrators.", "§2.4 p.8"),
    ("FR", "Expose model scores and next-best-action recommendations to the renewal journey APIs.", "§3.1 p.11"),
    ("FR", "Produce management dashboards for retention KPIs, lift and offer acceptance.", "§4.1 p.14"),
    ("NFR", "Model inference must complete within 500 ms at the 95th percentile for online renewals.", "§6.1 p.18"),
    ("NFR", "Encrypt PII and policy data at rest and in transit; host processing in India (Mumbai).", "§6.3 p.20"),
    ("NFR", "Provide explainability artefacts (top drivers) for regulated review of scoring decisions.", "§6.4 p.21"),
]
GENERIC_REQS = [
    ("FR", "Provide role-based workspaces for business users and administrators.", "§2.1 p.4"),
    ("FR", "Integrate with the client's identity provider using OIDC.", "§3.2 p.8"),
    ("FR", "Produce management dashboards for the agreed KPIs.", "§4.1 p.12"),
    ("NFR", "Target 99.9% monthly availability for user-facing services.", "§6.2 p.19"),
    ("NFR", "Encrypt data at rest and in transit.", "§6.3 p.20"),
]
REQ_PATTERN = re.compile(r"[^.!?\n]*\b(shall|must|should|is required to)\b[^.!?\n]*[.!?]", re.I)


def _src(project: dict) -> str:
    return (project.get("rfp_file") or "project brief")


def _context_blob(ctx: dict) -> str:
    project = ctx.get("project", {}) or {}
    parts = [
        project.get("industry", ""),
        project.get("name", ""),
        project.get("client", ""),
        project.get("scope", ""),
        ctx.get("rfp_text") or "",
        ctx.get("role") or "",
        ctx.get("agent") or "",
    ]
    for out in (ctx.get("upstream") or {}).values():
        if isinstance(out, dict):
            for r in out.get("requirements") or []:
                parts.append(str(r.get("text") or ""))
            parts.append(str(out.get("objective") or ""))
            parts.append(str(out.get("title") or ""))
    return " ".join(parts).lower()


def _pick_req_pack(ctx: dict) -> list[tuple[str, str, str]]:
    blob = _context_blob(ctx)
    project = ctx.get("project", {}) or {}
    if any(k in blob for k in ("retention", "renewal", "private car", "motor own damage", "propensity")):
        return RETENTION_REQS
    industry = (project.get("industry") or "").strip()
    if industry in DEFAULT_REQS:
        return DEFAULT_REQS[industry]
    if any(k in blob for k in ("insurance", "policy", "claims", "underwrit", "ergo", "hdfc")):
        return DEFAULT_REQS["Insurance"]
    if any(k in blob for k in ("bank", "loan", "credit", "bfsi")):
        return DEFAULT_REQS["BFSI"]
    if any(k in blob for k in ("hospital", "patient", "ehr", "clinic")):
        return DEFAULT_REQS["Healthcare"]
    return GENERIC_REQS


def _requirements(ctx: dict) -> dict:
    project = ctx.get("project", {})
    text = ctx.get("rfp_text") or ""
    found = [m.group(0).strip() for m in REQ_PATTERN.finditer(text)][:25]
    reqs = []
    if found:
        for i, s in enumerate(found, 1):
            nfr = bool(re.search(r"perform|secur|availab|encrypt|latency|uptime|complian|scal|residen", s, re.I))
            reqs.append({"id": f"REQ-{i:03d}", "text": s, "type": "NFR" if nfr else "FR",
                         "priority": "Must" if re.search(r"shall|must", s, re.I) else "Should",
                         "category": "Extracted", "source": {"document": _src(project), "locator": f"sentence {i}"},
                         "confidence": 0.86})
    else:
        for i, (t, s, loc) in enumerate(_pick_req_pack(ctx), 1):
            reqs.append({"id": f"REQ-{i:03d}", "text": s, "type": t, "priority": "Must", "category": "Core",
                         "source": {"document": _src(project), "locator": loc}, "confidence": round(0.8 + (i % 4) * 0.04, 2)})
    clar = [c["question"] for c in project.get("clarifications", []) if c.get("open")]
    constraints = [
        f"Hosting region: {project.get('region', 'client region')}",
        f"Response deadline: {project.get('deadline', 'TBC')}",
    ]
    if "retention" in _context_blob(ctx):
        constraints.append("Model outputs must support regulated explainability for renewal decisions.")
    return {
        "requirements": reqs,
        "constraints": constraints,
        "evaluation_criteria": ["Solution fit", "Delivery approach", "Commercials", "Team experience", "Model governance"],
        "clarifications": clar,
        "deadlines": [f"Submission {project.get('deadline', 'TBC')}"],
    }


def _reqs_from(ctx: dict) -> list[dict]:
    for out in ctx.get("upstream", {}).values():
        if isinstance(out, dict) and "requirements" in out:
            return out["requirements"]
    return _requirements(ctx)["requirements"]


def _upstream_labels(ctx: dict) -> list[str]:
    labels = []
    for key, out in (ctx.get("upstream") or {}).items():
        if not isinstance(out, dict):
            continue
        if "requirements" in out:
            labels.append(f"{key}: {len(out.get('requirements') or [])} requirements")
        elif out.get("title"):
            labels.append(f"{key}: {out.get('title')}")
        elif out.get("recommended"):
            labels.append(f"{key}: architecture → {out.get('recommended')}")
        else:
            labels.append(str(key))
    return labels


def mock_output(template_id: str, ctx: dict[str, Any]) -> dict[str, Any]:
    project = ctx.get("project", {})
    name = project.get("name", "the programme")
    client = project.get("client", "the client")
    reqs = _reqs_from(ctx) if template_id != "RFP_INTELLIGENCE" else []
    src = {"document": _src(project), "locator": "§1.2"}

    lineage = _upstream_labels(ctx)
    if template_id == "RFP_INTELLIGENCE":
        data = _requirements(ctx)
    elif template_id == "BRD_AUTHOR":
        frs = [r for r in reqs if r["type"] == "FR"]
        nfrs = [r for r in reqs if r["type"] == "NFR"]
        objective = project.get("scope") or f"Deliver {name} for {client}."
        if lineage:
            objective = f"{objective.rstrip('.')} — enriched from upstream: {'; '.join(lineage)}."
        sections = [
            {"heading": "Inputs from prior agents", "body": "", "bullets": lineage or ["No prior agent output on the path — used project brief only."], "sources": [src]},
            {"heading": "Functional requirements", "bullets": [f"{r['id']}: {r['text']}" for r in frs], "sources": [r["source"] for r in frs]},
            {"heading": "Non-functional requirements", "bullets": [f"{r['id']}: {r['text']}" for r in nfrs], "sources": [r["source"] for r in nfrs]},
            {"heading": "Assumptions and dependencies", "bullets": ["Client provides test data within 5 working days", "Requirements freeze at BRD sign-off", "Prior agent outputs are authoritative inputs for this BRD"]},
        ]
        data = {"title": f"BRD — {name}", "objective": objective, "sections": sections,
                "traceability": {r["id"]: ("Functional requirements" if r["type"] == "FR" else "Non-functional requirements") for r in reqs}}
    elif template_id == "SOW_AUTHOR":
        assumptions = [
            "Client provides environments and test data",
            "Changes after BRD sign-off follow change control",
            "Cloud usage beyond the estimated scenario is billed at actuals",
        ]
        if lineage:
            assumptions.insert(0, f"Scope derived from upstream agents: {'; '.join(lineage)}")
        data = {"title": f"Statement of Work — {name}", "scope": project.get("scope") or name,
                "deliverables": ["Business Requirements Document", "Solution architecture and ADRs", "Working software per milestone", "Test evidence and runbooks"],
                "milestones": ["M1 Discovery and BRD sign-off", "M2 Architecture baseline", "M3 Build complete", "M4 UAT sign-off and go-live"],
                "assumptions": assumptions,
                "exclusions": ["Hardware procurement", "Data migration beyond stated volumes", "24x7 support after hypercare"],
                "acceptance": "Each deliverable is accepted against its linked requirements within 5 working days of submission.",
                "sources": [src]}
    elif template_id == "SOLUTION_ARCHITECT":
        integrations = ["Identity provider (OIDC)", "System of record", "Document store", "Observability stack"]
        if any("retention" in (r.get("text") or "").lower() for r in reqs):
            integrations = ["Policy admin / PAS", "Claims system", "Digital renewal journey APIs", "Feature store / model scoring", "Identity provider (OIDC)", "Observability stack"]
        data = {"recommended": "Modular services on managed containers",
                "options": [
                    {"name": "Modular services on managed containers", "summary": "Containerised services, managed PostgreSQL + pgvector, object storage, SSO." + (f" Builds on {lineage[0]}." if lineage else ""), "scores": {"scalability": 4, "time_to_market": 4, "cost": 4, "compliance": 5, "ops_effort": 4}},
                    {"name": "Modular monolith", "summary": "Single deployable with module boundaries; fastest MVP.", "scores": {"scalability": 3, "time_to_market": 5, "cost": 5, "compliance": 4, "ops_effort": 5}},
                    {"name": "Event-driven serverless", "summary": "Functions and queues; pay per use.", "scores": {"scalability": 5, "time_to_market": 3, "cost": 4, "compliance": 3, "ops_effort": 3}}],
                "integrations": integrations,
                "nfr_coverage": [f"{r['id']} covered by platform controls" for r in reqs if r["type"] == "NFR"]
                              or ([f"Inherited NFR coverage from {x}" for x in lineage] if lineage else []),
                "adr": "ADR-001: Adopt modular services on managed containers for compliance and balanced cost"
                       + (f" using inputs from {', '.join(lineage)}." if lineage else ".")}
    elif template_id == "TECH_ADVISOR":
        rows = [("Web/API", "Next.js + FastAPI", "Managed containers", "managed"),
                ("Relational + vector DB", "PostgreSQL + pgvector", "Managed PostgreSQL", "managed"),
                ("Object storage", "MinIO (licence review)", "Cloud object storage", "managed"),
                ("Identity", "Keycloak", "Entra ID", "managed"),
                ("Agent workflow", "Open-source agent framework", "Deploy on container platform", "open_source"),
                ("Monitoring", "Prometheus + Grafana", "Cloud monitoring", "open_source"),
                ("CI/CD", "GitHub Actions", "Cloud build pipelines", "open_source")]
        data = {"choices": [{"need": a, "open_source": b, "managed": c, "recommendation": d,
                             "rationale": "Lower operations effort" if d == "managed" else "No licence cost; team already skilled"} for a, b, c, d in rows]}
    elif template_id == "EFFORT_ESTIMATOR":
        n = max(1, len(reqs))
        scale = min(2.0, 0.6 + n / 10)
        data = {"phases": ["Discovery & BRD", "Architecture & setup", "Build", "UAT & rollout"],
                "role_lines": [
                    {"role": "Solution Architect", "fte": 0.5, "months": 3, "rationale": "Design authority across phases"},
                    {"role": "Frontend Engineer", "fte": round(1.0 * scale, 2), "months": 3},
                    {"role": "Python / AI Engineer", "fte": round(1.5 * scale, 2), "months": 3},
                    {"role": "Platform Engineer", "fte": 0.75, "months": 3},
                    {"role": "QA Engineer", "fte": 1.0, "months": 2.5},
                    {"role": "Business Analyst", "fte": 0.75, "months": 3},
                    {"role": "Security Reviewer", "fte": 0.2, "months": 1},
                    {"role": "Project Manager", "fte": 0.5, "months": 3}],
                "assumptions": [
                    f"{n} requirements in scope",
                    "Two-week sprints",
                    "Client SMEs available 4 hours a week",
                    *( [f"Effort scaled from upstream: {'; '.join(lineage)}"] if lineage else [] ),
                ],
                "confidence": "medium" if n > 3 else "low"}
    elif template_id == "CLOUD_FINOPS":
        data = {"workload": {"region": project.get("region") or "India (Mumbai)", "vcpu": 8, "instance_count": 3, "runtime_hours": 730,
                             "storage_gb": 500, "storage_class": "Standard", "requests_millions": 20, "llm_tokens_millions": 40,
                             "egress_gb": 200, "observability_gb": 50, "environments": 3, "commitment": "none"},
                "preferred_provider": "azure", "notes": ["Sizing assumes three environments; non-prod scaled to 40%."]}
    elif template_id == "COMMERCIAL_PRICING":
        data = {"model": "fixed_price" if project.get("delivery_model", "Fixed price").lower().startswith("fixed") else "time_and_materials",
                "target_margin_pct": 30, "discount_pct": 0, "commentary": "Standard margin; no discount requested."}
    elif template_id == "RESOURCE_PLANNER":
        people = ctx.get("availability") or []
        assignments, gaps = [], []
        for line in ["Solution Architect", "Frontend Engineer", "Python / AI Engineer", "Platform Engineer", "QA Engineer", "Business Analyst"]:
            match = next((p for p in people if p.get("role") == line and p.get("available_pct", 0) >= 40), None)
            if match:
                assignments.append({"role": line, "person": match["name"], "allocation_pct": min(100, match["available_pct"]), "verified": True})
            elif people:
                gaps.append(line)
            else:
                assignments.append({"role": line, "person": "TBD (HRMS not connected)", "allocation_pct": 100, "verified": False})
        data = {"assignments": assignments, "gaps": gaps}
    elif template_id == "GOVERNANCE_REVIEWER":
        findings = [{"severity": "info", "message": f"{len(reqs)} requirements cite a source document."}]
        if any(not r.get("source") for r in reqs):
            findings.append({"severity": "blocker", "message": "Some requirements have no source reference."})
        findings.append({"severity": "info", "message": "Pricing produced by the deterministic engine; awaiting commercial approval."})
        data = {"findings": findings, "evidence_complete": all(r.get("source") for r in reqs), "recommendation": "approve"}
    else:
        raise KeyError(template_id)

    # Validate before returning so mocks can never drift from the schema.
    from .registry import get_template
    model = output_model(get_template(template_id).output_schema)
    return model.model_validate(data).model_dump()
