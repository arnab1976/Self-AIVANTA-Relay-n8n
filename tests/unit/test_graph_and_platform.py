import pytest
from aivanta_connectors import UploadRejected, ingest, redact_pii
from aivanta_docs import artifact_to_document, render
from aivanta_graph import TEMPLATES, CanvasGraph, Edge, ToolPolicy, ValidationPolicy, diff, edge_problem, template_graph, validate
from aivanta_templates import load_templates, mock_output, output_model

POLICY = ValidationPolicy(tools={"document_reader": ToolPolicy(True, False), "ocr_parser": ToolPolicy(True, False), "object_store": ToolPolicy(True, False),
                                 "template_renderer": ToolPolicy(True, True), "sharepoint_search": ToolPolicy(True, False), "cloud_pricing": ToolPolicy(True, False),
                                 "hrms_availability": ToolPolicy(True, False), "jira_backlog": ToolPolicy(True, True), "email_send": ToolPolicy(False, True)})


@pytest.mark.parametrize("key", [k for k in TEMPLATES if k != "BLANK"])
def test_all_templates_validate(key):
    rep = validate(template_graph(key), POLICY)
    assert rep.ok, rep.summary()


def codes(g):
    return {i.code for i in validate(g, POLICY).issues}


def test_validation_rules():
    g = template_graph("RFP_SOW")
    g.edges = [e for e in g.edges if e.target != "final"]  # remove the final approval -> export path breaks
    assert "unreachable" in codes(g) or "no_terminal_path" in codes(g)

    g2 = template_graph("RES_DEPLOY")
    g2.edges = [e for e in g2.edges if not (e.source == "sapp")] + [Edge(id="x", source="res", target="jira")]
    g2.nodes = [n for n in g2.nodes if n.id != "sapp"]
    assert "external_without_approval" in codes(g2)

    g3 = template_graph("CLOUD_REVIEW")
    g3.node("tech").config["model_profile"] = "experimental-preview"
    g3.node("tech").config["tools"] = ["email_send"]
    assert {"model_not_allowed", "tool_not_approved"} <= codes(g3)

    g4 = template_graph("RFP_BRD")
    g4.node("upload").config["credential_ref"] = "password=hunter2"
    assert {"inline_credential", "inline_secret"} <= codes(g4)

    g5 = template_graph("CLOUD_REVIEW")
    g5.edges.append(Edge(id="loop", source="fin", target="tech"))
    assert "cycle" in codes(g5)


def test_edge_problem_and_hash_and_diff():
    g = template_graph("RFP_SOW")
    assert edge_problem(g, "rfp", "start") and edge_problem(g, "end", "rfp") and edge_problem(g, "brd", "kb")
    assert edge_problem(g, "rfp", "gap")  # duplicate
    assert "cycle" in edge_problem(g, "brd", "rfp")
    assert edge_problem(g, "brd", "sow") is None
    h = g.content_hash()
    g.nodes[0].position.x += 500
    assert g.content_hash() == h  # positions are design-time only
    new = template_graph("RFP_SOW")
    new.node("fin").config["timeout_s"] = 240
    d = diff(g, new)
    assert d["nodes_changed"][0]["fields"] == ["timeout_s"]


def test_templates_and_mocks_are_schema_valid():
    tpls = load_templates()
    assert len(tpls) == 10
    ctx = {"project": {"name": "X", "client": "Y", "industry": "BFSI", "clarifications": []}, "upstream": {}, "rfp_text": ""}
    for t in tpls.values():
        output_model(t.output_schema).model_validate(mock_output(t.id, ctx))


def test_ingest_scan_and_redaction():
    with pytest.raises(UploadRejected):
        ingest(b"MZ\x00\x00", "x.pdf")
    with pytest.raises(UploadRejected):
        ingest(b"hello", "x.exe")
    text, counts = redact_pii("Mail a.b@c.com, PAN ABCDE1234F, phone +91 98765 43210")
    assert counts == {"email": 1, "phone": 1, "pan": 1} and "a.b@c.com" not in text


def test_document_rendering_includes_evidence():
    art = {"type": "SOW", "version": 2, "approval_state": "approved", "run_id": "r1", "graph_version": "v3", "source_ids": ["RFP.pdf §3.1"],
           "content": {"title": "SOW", "scope": "Scope", "deliverables": ["BRD"], "milestones": ["M1"], "assumptions": ["A1"], "exclusions": ["E1"],
                       "acceptance": "Accepted in 5 days", "sources": [{"document": "RFP.pdf", "locator": "§3.1"}]}}
    doc = artifact_to_document(art, {"code": "P1", "client": "C", "name": "N"})
    assert doc["assumptions"] == ["A1"] and doc["review_status"] == "approved" and doc["sources"]
    for fmt in ("docx", "pdf", "xlsx"):
        data, mime = render(doc, fmt)
        assert len(data) > 1000 and mime
