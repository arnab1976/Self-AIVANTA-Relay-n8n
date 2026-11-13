"""AIVANTA canvas graph schema, validation, templates and diff."""
from .models import NODE_TYPES, SCHEMA_VERSION, CanvasGraph, Edge, Node, Position
from .templates import TEMPLATES, default_config, template_graph
from .validate import Issue, ToolPolicy, ValidationPolicy, ValidationReport, edge_problem, validate


def diff(old: CanvasGraph, new: CanvasGraph) -> dict:
    """Structural diff between two graph versions (positions ignored)."""
    on = {n.id: n for n in old.nodes}
    nn = {n.id: n for n in new.nodes}
    key = lambda e: (e.source, e.target, e.label or "")  # noqa: E731
    oe = {key(e) for e in old.edges}
    ne = {key(e) for e in new.edges}
    changed = []
    for nid in sorted(set(on) & set(nn)):
        a, b = on[nid], nn[nid]
        fields = sorted(k for k in set(a.config) | set(b.config) if a.config.get(k) != b.config.get(k))
        if a.name != b.name:
            fields.insert(0, "name")
        if fields:
            changed.append({"id": nid, "name": b.name, "fields": fields})
    return {
        "nodes_added": [{"id": i, "name": nn[i].name, "type": nn[i].type} for i in sorted(set(nn) - set(on))],
        "nodes_removed": [{"id": i, "name": on[i].name, "type": on[i].type} for i in sorted(set(on) - set(nn))],
        "nodes_changed": changed,
        "edges_added": [{"source": s, "target": t, "label": lab} for s, t, lab in sorted(ne - oe)],
        "edges_removed": [{"source": s, "target": t, "label": lab} for s, t, lab in sorted(oe - ne)],
    }


__all__ = ["NODE_TYPES", "SCHEMA_VERSION", "CanvasGraph", "Edge", "Node", "Position", "TEMPLATES", "default_config",
           "template_graph", "Issue", "ToolPolicy", "ValidationPolicy", "ValidationReport", "edge_problem", "validate", "diff"]
