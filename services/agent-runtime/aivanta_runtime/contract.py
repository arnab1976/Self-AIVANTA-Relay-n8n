"""Runtime contract shared by AIVANTA Conductor (LangGraph) and AIVANTA
Ensemble (AutoGen). The API, database and web app only talk to this
interface, which keeps the portal decoupled from any one agent framework
(blueprint section 19).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from aivanta_connectors import ToolContext, ToolGateway
from aivanta_graph import CanvasGraph
from pydantic import BaseModel

from .llm_settings import LLMSettings

EventType = Literal[
    "run_started", "run_resumed", "run_succeeded", "run_failed", "run_cancelled",
    "node_started", "node_succeeded", "node_skipped", "node_failed", "node_retry",
    "route_selected", "approval_requested", "approval_decided", "agent_message", "tool_called",
]
NodeState = Literal["pending", "running", "succeeded", "skipped", "failed", "approval", "cancelled"]
Emit = Callable[[EventType, str | None, dict[str, Any]], Awaitable[None]]


class Decision(BaseModel):
    decision: Literal["Approved", "Rejected"]
    by: str
    role: str
    comment: str = ""


class RunOutcome(BaseModel):
    status: Literal["succeeded", "awaiting_approval", "failed", "cancelled"]
    node_status: dict[str, str] = {}
    outputs: dict[str, Any] = {}
    pending_approvals: list[dict[str, Any]] = []
    error: str | None = None
    metrics: dict[str, Any] = {}


@dataclass
class RunContext:
    run_id: str
    tenant_id: str
    project: dict[str, Any]
    graph: CanvasGraph
    graph_version: str
    mode: Literal["published", "simulation"]
    gateway: ToolGateway
    approved_tools: set[str]
    emit: Emit
    pricing: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    cloud: Callable[[dict[str, Any]], dict[str, Any]]
    retrieve: Callable[[str, int], list[dict[str, Any]]]
    llm: LLMSettings
    is_cancelled: Callable[[], bool] = lambda: False
    load_state: Callable[[], dict[str, Any]] = lambda: {}
    save_state: Callable[[dict[str, Any]], None] = lambda s: None
    agent_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    idempotency_prefix: str = ""
    fx_rate: float = 1.0

    def tool_context(self, node_id: str) -> ToolContext:
        return ToolContext(tenant_id=self.tenant_id, project_id=self.project["id"], run_id=self.run_id, node_id=node_id,
                           approved_tools=self.approved_tools, idempotency_prefix=self.idempotency_prefix or self.run_id)


class RuntimeAdapter(ABC):
    """Compile a validated canvas graph and execute it."""

    name: str = "abstract"
    framework: str = ""

    @abstractmethod
    def framework_version(self) -> str: ...

    @abstractmethod
    async def start(self, ctx: RunContext) -> RunOutcome:
        """Run until the graph completes, fails, or pauses at Human Approval nodes."""

    @abstractmethod
    async def resume(self, ctx: RunContext, decisions: dict[str, Decision]) -> RunOutcome:
        """Continue a paused run after approval decisions (keyed by node id)."""

    @abstractmethod
    async def retry_failed(self, ctx: RunContext) -> RunOutcome:
        """Resume a failed run from its last persisted checkpoint without repeating completed steps."""

    @abstractmethod
    def export(self, graph: CanvasGraph) -> dict[str, Any]:
        """Runtime-native export of the compiled workflow (e.g. Mermaid for LangGraph, AutoGen Studio JSON for AutoGen)."""
