"""The canvas → n8n compiler produces importable, correctly wired workflows."""
from __future__ import annotations

import json

import pytest
from aivanta_graph import TEMPLATES, Edge, template_graph
from aivanta_runtime.n8n_compiler import CompileError, CompileOptions, compile_workflow, node_map


def _wf(key="RFP_SOW", mode="native"):
    return compile_workflow(template_graph(key), CompileOptions(agent_mode=mode, workflow_name=f"t-{key}", webhook_path=f"aivanta/t/{key}"))


def by_type(wf, suffix):
    return [n for n in wf["nodes"] if n["type"].endswith(suffix)]


@pytest.mark.parametrize("key", [k for k in TEMPLATES if k != "BLANK"])
@pytest.mark.parametrize("mode", ["native", "service"])
def test_every_template_compiles(key, mode):
    wf = _wf(key, mode)
    json.dumps(wf)                                               # serialisable for the n8n public API
    names = [n["name"] for n in wf["nodes"]]
    assert len(names) == len(set(names))                         # n8n requires unique node names
    assert wf["settings"]["executionOrder"] == "v1"
    for src, outs in wf["connections"].items():
        assert src in names
        for kind, groups in outs.items():
            for group in groups:
                assert all(t["node"] in names and t["type"] == kind for t in group)
    g = template_graph(key)
    assert len(by_type(wf, ".wait")) == sum(1 for n in g.nodes if n.type == "approval")
    assert len(by_type(wf, ".switch")) == sum(1 for n in g.nodes if n.type == "decision")
    agents = sum(1 for n in g.nodes if n.type == "agent")
    assert len(by_type(wf, "langchain.agent")) == (agents if mode == "native" else 0)


def test_rfp_to_sow_wiring():
    wf = _wf()
    names = {n["name"] for n in wf["nodes"]}
    trig = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.webhook")
    assert trig["parameters"]["authentication"] == "headerAuth" and trig["parameters"]["responseMode"] == "onReceived"
    sw = next(n for n in wf["nodes"] if n["type"].endswith(".switch"))
    assert [r["outputKey"] for r in sw["parameters"]["rules"]["values"]] == ["gaps found", "no gaps"]
    # BRD Author: "gaps found → clarification approved" and "no gaps" are alternatives → no Join node
    assert "Join · BRD Author" not in names
    # Solution Architect also takes the prior-proposals knowledge base in parallel → Join with 2 inputs
    join = next(n for n in wf["nodes"] if n["name"] == "Join · Solution Architect")
    assert join["parameters"]["numberInputs"] == 2
    # each AI Agent node has an OpenAI chat model sub-node on the AIVANTA gateway credential
    for agent in (n for n in wf["nodes"] if n["type"].endswith("langchain.agent")):
        model_src = [s for s, o in wf["connections"].items() if any(t["node"] == agent["name"] for t in (o.get("ai_languageModel") or [[]])[0])]
        assert len(model_src) == 1
        model = next(n for n in wf["nodes"] if n["name"] == model_src[0])
        assert model["credentials"]["openAiApi"]["name"] == "AIVANTA Model Gateway"
    # every bridge call carries the run id, node id and execution id, and runs once per execution
    for n in (x for x in wf["nodes"] if x["type"] == "n8n-nodes-base.httpRequest"):
        assert "/internal/n8n/" in n["parameters"]["url"] and n["executeOnce"] is True
        body = n["parameters"]["jsonBody"]
        assert "run_id" in body and "node_id" in body and "$execution.id" in body
    approval_req = [n for n in wf["nodes"] if n["parameters"].get("url", "").endswith("/approval_request")]
    assert approval_req and all("$execution.resumeUrl" in n["parameters"]["jsonBody"] for n in approval_req)
    assert set(node_map(wf)) >= {"start", "rfp", "gap", "clar", "price", "end"}


def test_retry_budget_maps_to_n8n_retry_on_fail():
    g = template_graph("CLOUD_REVIEW")
    g.node("tech").config["retry"] = 2
    wf = compile_workflow(g, CompileOptions(agent_mode="service"))
    tech = next(n for n in wf["nodes"] if "node tech" in n.get("notes", ""))
    assert tech["retryOnFail"] is True and tech["maxTries"] == 3


def test_cycles_are_rejected():
    g = template_graph("CLOUD_REVIEW")
    g.edges.append(Edge(id="loop", source="fin", target="tech"))
    with pytest.raises(CompileError):
        compile_workflow(g)
