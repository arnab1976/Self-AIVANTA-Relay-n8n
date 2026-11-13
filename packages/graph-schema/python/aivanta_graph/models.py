"""Canvas graph schema (canvas.v1).

The AIVANTA canvas owns this schema. The browser stores node positions and
connections; the server stores validated, immutable versions of it. Agent
runtimes (LangGraph in Conductor, AutoGen in Ensemble) only ever receive a
validated, published graph and compile it through their adapter.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

NodeType = Literal["start", "end", "agent", "tool", "decision", "approval", "data", "calc"]
NODE_TYPES: tuple[str, ...] = ("start", "end", "agent", "tool", "decision", "approval", "data", "calc")
SCHEMA_VERSION = "canvas.v1"


class Position(BaseModel):
    x: float = 0
    y: float = 0


class Node(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    type: NodeType
    name: str = Field(min_length=1, max_length=120)
    position: Position = Field(default_factory=Position)
    config: dict[str, Any] = Field(default_factory=dict)


class Edge(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    source: str
    target: str
    label: str | None = None


class CanvasGraph(BaseModel):
    schema_version: str = SCHEMA_VERSION
    input_schema: str = "project.v1"
    output_schema: str = "proposal_package.v1"
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)

    # ---- helpers -------------------------------------------------------
    def node(self, node_id: str) -> Node | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def incoming(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.target == node_id]

    def outgoing(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.source == node_id]

    def canonical(self) -> dict[str, Any]:
        """Content used for hashing: positions are design-time only and excluded."""
        return {
            "schema_version": self.schema_version,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "nodes": sorted(
                ({"id": n.id, "type": n.type, "name": n.name, "config": n.config} for n in self.nodes),
                key=lambda n: n["id"],
            ),
            "edges": sorted(
                ({"source": e.source, "target": e.target, "label": e.label or ""} for e in self.edges),
                key=lambda e: (e["source"], e["target"], e["label"]),
            ),
        }

    def content_hash(self) -> str:
        raw = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def topological_order(self) -> list[str]:
        indeg = {n.id: 0 for n in self.nodes}
        for e in self.edges:
            if e.target in indeg:
                indeg[e.target] += 1
        ready = [n for n, d in indeg.items() if d == 0]
        order: list[str] = []
        while ready:
            cur = ready.pop(0)
            order.append(cur)
            for e in self.outgoing(cur):
                if e.target in indeg:
                    indeg[e.target] -= 1
                    if indeg[e.target] == 0:
                        ready.append(e.target)
        return order
