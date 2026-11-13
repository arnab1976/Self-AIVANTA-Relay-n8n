"""Tool registry (MCP gateway catalogue)."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    kind: str
    description: str
    endpoint: str
    scopes: tuple[str, ...]
    credential_ref: str
    timeout_s: int
    approved: bool
    external: bool
    input_schema: dict = field(default_factory=lambda: {
        "type": "object", "required": ["project_id", "run_id"],
        "properties": {"project_id": {"type": "string"}, "run_id": {"type": "string"}, "operation": {"type": "string"}, "payload": {"type": "object"}}})
    output_schema: dict = field(default_factory=lambda: {
        "type": "object", "properties": {"status": {"type": "string"}, "data": {"type": "object"}, "trace_id": {"type": "string"}}})


@lru_cache(maxsize=1)
def load_registry() -> dict[str, ToolDefinition]:
    data = yaml.safe_load((Path(__file__).parent / "tools.yaml").read_text(encoding="utf-8"))
    out = {}
    for t in data["tools"]:
        out[t["id"]] = ToolDefinition(id=t["id"], kind=t["kind"], description=t["description"], endpoint=t["endpoint"],
                                      scopes=tuple(t["scopes"]), credential_ref=t["credential_ref"], timeout_s=int(t["timeout_s"]),
                                      approved=bool(t["approved"]), external=bool(t["external"]))
    return out
