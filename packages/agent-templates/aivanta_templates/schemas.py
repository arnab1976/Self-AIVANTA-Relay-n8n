"""Typed artifacts exchanged between agents (blueprint section 8).

Every agent output must validate against one of these models before
downstream nodes may consume it.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    document: str = Field(description="Source file name or artifact id")
    locator: str = Field(description="Section, page or paragraph, e.g. '§3.4 p.11'")


class Requirement(BaseModel):
    id: str
    text: str
    type: Literal["FR", "NFR"]
    priority: Literal["Must", "Should", "Could"] = "Must"
    category: str = "General"
    source: SourceRef
    confidence: float = Field(ge=0, le=1, default=0.85)


class RequirementsDoc(BaseModel):
    requirements: list[Requirement]
    constraints: list[str] = []
    evaluation_criteria: list[str] = []
    clarifications: list[str] = []
    deadlines: list[str] = []


class Section(BaseModel):
    heading: str
    body: str = ""
    bullets: list[str] = []
    sources: list[SourceRef] = []


class BRD(BaseModel):
    title: str
    objective: str
    sections: list[Section]
    traceability: dict[str, str] = Field(default_factory=dict, description="requirement id -> BRD section heading")


class SOW(BaseModel):
    title: str
    scope: str
    deliverables: list[str]
    milestones: list[str]
    assumptions: list[str]
    exclusions: list[str]
    acceptance: str
    sources: list[SourceRef] = []


class ArchitectureOption(BaseModel):
    name: str
    summary: str
    scores: dict[str, int] = Field(default_factory=dict)


class ArchitectureProposal(BaseModel):
    recommended: str
    options: list[ArchitectureOption]
    integrations: list[str] = []
    nfr_coverage: list[str] = []
    adr: str = ""


class TechChoice(BaseModel):
    need: str
    open_source: str
    managed: str
    recommendation: Literal["open_source", "managed", "commercial"]
    rationale: str


class TechMatrix(BaseModel):
    choices: list[TechChoice]


class RoleLine(BaseModel):
    role: str
    fte: float = Field(ge=0)
    months: float = Field(ge=0)
    rationale: str = ""


class EffortPlan(BaseModel):
    phases: list[str]
    role_lines: list[RoleLine]
    assumptions: list[str] = []
    confidence: Literal["low", "medium", "high"] = "medium"


class WorkloadSizing(BaseModel):
    region: str = "India (Mumbai)"
    vcpu: int = 8
    instance_count: int = 3
    runtime_hours: int = 730
    storage_gb: int = 500
    storage_class: str = "Standard"
    requests_millions: float = 20
    llm_tokens_millions: float = 40
    egress_gb: float = 200
    observability_gb: float = 50
    environments: int = 3
    commitment: str = "none"


class CloudCostScenarios(BaseModel):
    workload: WorkloadSizing
    preferred_provider: Literal["aws", "gcp", "azure"] = "azure"
    notes: list[str] = []


class PricingWorksheet(BaseModel):
    model: Literal["fixed_price", "time_and_materials"] = "fixed_price"
    target_margin_pct: float = 30
    discount_pct: float = 0
    commentary: str = ""


class StaffingAssignment(BaseModel):
    role: str
    person: str
    allocation_pct: int
    verified: bool = True


class StaffingPlan(BaseModel):
    assignments: list[StaffingAssignment]
    gaps: list[str] = []


class Finding(BaseModel):
    severity: Literal["info", "warning", "blocker"]
    message: str


class ReviewFindings(BaseModel):
    findings: list[Finding]
    evidence_complete: bool
    recommendation: Literal["approve", "revise"]


OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "requirements.v1": RequirementsDoc,
    "brd.v1": BRD,
    "sow.v1": SOW,
    "architecture.v1": ArchitectureProposal,
    "tech_matrix.v1": TechMatrix,
    "effort.v1": EffortPlan,
    "cloud_cost.v1": CloudCostScenarios,
    "pricing.v1": PricingWorksheet,
    "staffing.v1": StaffingPlan,
    "review.v1": ReviewFindings,
}


def output_model(schema_id: str) -> type[BaseModel]:
    try:
        return OUTPUT_MODELS[schema_id]
    except KeyError as exc:  # pragma: no cover - guarded by validation
        raise KeyError(f"Unknown output schema '{schema_id}'") from exc
