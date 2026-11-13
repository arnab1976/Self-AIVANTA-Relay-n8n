"""Demo seed data: three tenants with projects, canvases and published versions."""
from __future__ import annotations

from aivanta_graph import template_graph
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..models import CanvasGraphRow, GraphVersion, Project, Tenant, ToolPolicy

RATE_ROLES = ["Solution Architect", "Frontend Engineer", "Python / AI Engineer", "Platform Engineer", "QA Engineer",
              "Business Analyst", "Security Reviewer", "Project Manager", "Blended team"]
RATES_INR = [320000, 170000, 230000, 190000, 120000, 150000, 260000, 240000, 180000]
RATES_USD = [14500, 8600, 11200, 9400, 6100, 7600, 12500, 10800, 9000]


def rate_card(currency: str) -> dict:
    return dict(zip(RATE_ROLES, RATES_USD if currency == "USD" else RATES_INR))


DEFAULT_ESTIMATE = {"role_lines": [{"role": "Solution Architect", "fte": 0.5, "months": 3}, {"role": "Frontend Engineer", "fte": 1.5, "months": 3},
                                   {"role": "Python / AI Engineer", "fte": 2, "months": 3}, {"role": "Platform Engineer", "fte": 0.75, "months": 3},
                                   {"role": "QA Engineer", "fte": 1, "months": 2.5}, {"role": "Business Analyst", "fte": 0.75, "months": 3}],
                    "target_margin_pct": 30, "discount_pct": 0, "overhead_pct": 8, "contingency_pct": 10, "licenses": 0, "travel": 0, "provider": "azure"}
DEFAULT_WORKLOAD = {"region": "India (Mumbai)", "vcpu": 8, "instance_count": 3, "runtime_hours": 730, "storage_gb": 500, "storage_class": "Standard",
                    "requests_millions": 20, "llm_tokens_millions": 40, "egress_gb": 200, "observability_gb": 50, "environments": 3, "commitment": "none"}


def create_tenant(db: Session, code: str, name: str, currency: str, region: str, isolation: str, idp: str = "Entra ID (OIDC)",
                  margin_floor: float = 22, allowed=None, snapshot="2026-10-20") -> Tenant:
    t = Tenant(code=code, name=name, currency=currency, region=region, isolation_model=isolation, identity_provider=idp,
               margin_floor_pct=margin_floor, discount_limit_pct=10, rate_card=rate_card(currency), rate_card_version="RC-2026.10-v3",
               fx_rate=84.0 if currency == "INR" else 1.0, fx_version="FX-2026-10-01", price_snapshot_date=snapshot,
               allowed_models=allowed or ["enterprise-reasoning", "enterprise-fast", "local-open-weight"],
               integrations={"sso": True, "crm": True, "hrms": currency == "INR", "jira": True, "sharepoint": True, "cloud_pricing": True})
    db.add(t)
    db.flush()
    db.add(ToolPolicy(tenant_id=t.id, tool_id="email_send", approved=False))
    audit.record(db, t.id, "system", "admin", "Tenant provisioned", f"{name} · {isolation}")
    return t


def add_graph(db: Session, t: Tenant, key: str, name: str, publish_as: list[str] | None = None, by: str = "seed") -> CanvasGraphRow:
    g = template_graph(key)
    row = CanvasGraphRow(tenant_id=t.id, name=name, template=key, draft=g.model_dump(), created_by=by)
    db.add(row)
    db.flush()
    for i, env in enumerate(publish_as or [], 1):
        db.add(GraphVersion(tenant_id=t.id, graph_id=row.id, version=i, content=g.model_dump(), content_hash=g.content_hash(),
                            environment=env, published_by=by))
        audit.record(db, t.id, by, "architect", "Graph version published", f"{name} v{i} · {g.content_hash()}")
    return row


def seed_demo(db: Session) -> None:
    if db.scalars(select(Tenant)).first():
        return
    t1 = create_tenant(db, "FP", "Feuji — Presales CoE", "INR", "India (Mumbai)", "schema-per-tenant")
    t2 = create_tenant(db, "US", "Feuji — US Delivery", "USD", "US East", "dedicated-database", margin_floor=25, snapshot="2026-09-12")
    t3 = create_tenant(db, "HX", "Partner Sandbox — Helios", "INR", "India (Mumbai)", "row-level-security", idp="Partner IdP (OIDC)",
                       margin_floor=20, allowed=["enterprise-fast", "local-open-weight"])
    projects = [
        (t1, "PRJ-1042", "Meridian Bank", "Loan Origination Modernization", "BFSI", "Solutioning",
         "Digital loan origination across web, mobile and branch; core banking and bureau integration.", True),
        (t1, "PRJ-1046", "Coastal Life Insurance", "Claims Intelligence Portal", "Insurance", "RFP received",
         "FNOL capture, claims triage, fraud scoring and surveyor allocation.", False),
        (t2, "US-2211", "St. Clare Health Network", "Patient Engagement Platform", "Healthcare", "Proposal",
         "Scheduling, reminders and EHR (FHIR R4) integration across 40 clinics.", True),
        (t3, "HX-0107", "Arcadia Pharma", "Regulatory Submission Assistant", "Pharma", "Qualify",
         "Module 2 drafting from clinical study reports with citations; GxP validation evidence.", False),
    ]
    for t, code, client, name, ind, stage, scope, gap in projects:
        db.add(Project(tenant_id=t.id, code=code, client=client, name=name, industry=ind, deal_stage=stage, scope=scope, region=t.region,
                       currency=t.currency, deadline="2026-11-30", owner="Seed data", estimate_inputs=DEFAULT_ESTIMATE,
                       workload={**DEFAULT_WORKLOAD, "region": t.region},
                       clarifications=[{"question": "Is data migration of legacy records in scope?", "open": gap},
                                       {"question": "Which identity provider must the solution federate with?", "open": False}]))
    add_graph(db, t1, "RFP_SOW", "RFP-to-SOW", ["prod", "staging"])
    add_graph(db, t1, "CLOUD_REVIEW", "Cloud Cost Review")
    add_graph(db, t1, "RES_DEPLOY", "Resource Deployment", ["staging"])
    add_graph(db, t2, "RFP_SOW", "RFP-to-SOW", ["prod"])
    add_graph(db, t2, "EST_PROP", "Estimate-to-Proposal")
    g3 = template_graph("RFP_BRD")
    for n in g3.nodes:
        if n.type == "agent":
            n.config["model_profile"] = "local-open-weight"
    row = CanvasGraphRow(tenant_id=t3.id, name="RFP-to-BRD", template="RFP_BRD", draft=g3.model_dump(), created_by="seed")
    db.add(row)
    db.flush()
    db.add(GraphVersion(tenant_id=t3.id, graph_id=row.id, version=1, content=g3.model_dump(), content_hash=g3.content_hash(), environment="dev", published_by="seed"))
    db.commit()
