"""Live tests against a real n8n and a running AIVANTA Relay API (N8N_MODE=rest).

    export LIVE_API=http://localhost:8000            # API started with N8N_MODE=rest
    LIVE_N8N=1 pytest -q tests/live

They publish templates, run them through n8n, decide every approval as the
designated role and check the n8n executions through the n8n public API.
"""
from __future__ import annotations

import os
import time

import httpx
import pytest

pytestmark = pytest.mark.skipif(os.getenv("LIVE_N8N") != "1", reason="set LIVE_N8N=1 with a running API (N8N_MODE=rest) and n8n")
API = os.getenv("LIVE_API", "http://localhost:8000")
N8N = os.getenv("N8N_API_URL", "http://localhost:5678/api/v1")


def login(c: httpx.Client, role: str, tenant: str = "FP") -> dict:
    r = c.post(f"{API}/api/auth/dev-login", json={"tenant_code": tenant, "role": role, "name": f"Live {role}"})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def wait(c: httpx.Client, hdr: dict, run_id: str, until: set[str], timeout: float = 180) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"{API}/api/runs/{run_id}", headers=hdr).json()
        if r["status"] in until:
            return r
        time.sleep(0.5)
    raise AssertionError(f"run {run_id} stuck in {r['status']}: {r.get('error')}")


def run_template(c: httpx.Client, template: str, open_clarifications: bool) -> dict:
    ps, arch = login(c, "presales"), login(c, "architect")
    proj = c.post(f"{API}/api/projects", headers=ps, json={"client": "Live Bank", "name": f"Live {template}", "industry": "BFSI", "scope": "Live n8n test"}).json()
    c.patch(f"{API}/api/projects/{proj['id']}", headers=ps, json={"clarifications": [{"question": "Migration in scope?", "open": open_clarifications}]})
    g = c.post(f"{API}/api/graphs", headers=arch, json={"name": f"Live {template} {time.time():.0f}", "template": template}).json()
    c.put(f"{API}/api/graphs/{g['id']}", headers=arch, json={"draft": g["draft"]}).raise_for_status()
    c.post(f"{API}/api/graphs/{g['id']}/publish", headers=arch).raise_for_status()
    run = c.post(f"{API}/api/runs", headers=ps, json={"graph_id": g["id"], "project_id": proj["id"], "version": 1}).json()
    decided: list[str] = []
    while True:
        r = wait(c, ps, run["id"], {"awaiting_approval", "succeeded", "failed", "cancelled"})
        if r["status"] != "awaiting_approval":
            return {**r, "decided": decided}
        pend = [a for a in c.get(f"{API}/api/approvals?status=Pending", headers=ps).json() if a["run_id"] == run["id"]]
        assert pend, r
        a = pend[0]
        role = a["approver_role"]
        hdr = login(c, role)
        res = c.post(f"{API}/api/approvals/{a['id']}/decide", headers=hdr, json={"decision": "Approved", "comment": "live"})
        assert res.status_code == 200, res.text
        decided.append(a["node_id"])
        time.sleep(0.5)


@pytest.mark.parametrize("template,gaps", [("CLOUD_REVIEW", False), ("RES_DEPLOY", False), ("RFP_SOW", True), ("RFP_SOW", False)])
def test_template_runs_on_real_n8n(template, gaps):
    with httpx.Client(timeout=60) as c:
        r = run_template(c, template, gaps)
        assert r["status"] == "succeeded", r
        assert r["runtime_ref"]["mode"] == "rest" and r["runtime_ref"]["execution_id"]
        key = os.getenv("N8N_API_KEY", "")
        ex = c.get(f"{N8N}/executions/{r['runtime_ref']['execution_id']}", headers={"X-N8N-API-KEY": key}).json()
        assert ex["status"] == "success" and str(ex["workflowId"]) == str(r["runtime_ref"]["workflow_id"])
        if template == "RFP_SOW":
            assert r["node_status"]["clar"] == ("succeeded" if gaps else "skipped")
            assert ("clar" in r["decided"]) is gaps


def _publish(c, arch, template, mutate=None):
    g = c.post(f"{API}/api/graphs", headers=arch, json={"name": f"Live {template} {time.time():.3f}", "template": template}).json()
    draft = g["draft"]
    if mutate:
        mutate(draft)
    c.put(f"{API}/api/graphs/{g['id']}", headers=arch, json={"draft": draft}).raise_for_status()
    c.post(f"{API}/api/graphs/{g['id']}/publish", headers=arch).raise_for_status()
    return g


def test_rejection_and_retry_from_failed_node_on_real_n8n():
    with httpx.Client(timeout=60) as c:
        ps, arch = login(c, "presales"), login(c, "architect")
        proj = c.get(f"{API}/api/projects", headers=ps).json()[0]

        # 1) rejected approval → run fails, End skipped
        g = _publish(c, arch, "CLOUD_REVIEW")
        run = c.post(f"{API}/api/runs", headers=ps, json={"graph_id": g["id"], "project_id": proj["id"], "version": 1}).json()
        r = wait(c, ps, run["id"], {"awaiting_approval"})
        a = next(x for x in c.get(f"{API}/api/approvals?status=Pending", headers=ps).json() if x["run_id"] == run["id"])
        c.post(f"{API}/api/approvals/{a['id']}/decide", headers=login(c, a["approver_role"]), json={"decision": "Rejected", "comment": "too high"}).raise_for_status()
        r = wait(c, ps, run["id"], {"failed", "succeeded"})
        assert r["status"] == "failed" and r["node_status"]["end"] == "skipped" and "rejected" in (r["error"] or "")

        # 2) a node fails with no retry budget → run fails; retry resumes in n8n from the failed node only
        def mutate(d):
            n = next(x for x in d["nodes"] if x["id"] == "fin")
            n["config"].update(fail_simulation=True, retry=0)
        g = _publish(c, arch, "CLOUD_REVIEW", mutate)
        run = c.post(f"{API}/api/runs", headers=ps, json={"graph_id": g["id"], "project_id": proj["id"], "version": 1}).json()
        r = wait(c, ps, run["id"], {"failed", "awaiting_approval", "succeeded"})
        assert r["status"] == "failed" and r["node_status"]["tech"] == "succeeded", r
        first_exec = r["runtime_ref"]["execution_id"]
        events_before = [e for e in c.get(f"{API}/api/runs/{run['id']}/events", headers=ps).json() if e["type"] == "node_started" and e["node_id"] == "tech"]
        c.post(f"{API}/api/runs/{run['id']}/retry", headers=ps).raise_for_status()
        r = wait(c, ps, run["id"], {"awaiting_approval", "failed", "succeeded"})
        assert r["status"] == "awaiting_approval", r
        assert r["runtime_ref"]["execution_id"] != first_exec          # n8n created a retry execution
        events_after = [e for e in c.get(f"{API}/api/runs/{run['id']}/events", headers=ps).json() if e["type"] == "node_started" and e["node_id"] == "tech"]
        assert len(events_after) == len(events_before)                 # completed steps were not repeated
