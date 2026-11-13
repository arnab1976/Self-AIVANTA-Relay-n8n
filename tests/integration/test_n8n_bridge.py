"""HTTP contract between n8n and AIVANTA: bridge steps, idempotency and the model gateway."""
from __future__ import annotations

import os

def login(client, tenant="FP", role="presales", name=None) -> dict:
    r = client.post("/api/auth/dev-login", json={"tenant_code": tenant, "role": role, "name": name or f"{role.title()} Tester"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


TOKEN = {"X-Aivanta-Bridge-Token": os.environ.get("AIVANTA_BRIDGE_TOKEN", "change-me")}


def _paused_run(client):
    ps = login(client, role="presales")
    arch = login(client, role="architect")
    proj = client.get("/api/projects", headers=ps).json()[0]
    g = client.post("/api/graphs", headers=arch, json={"name": "Bridge test", "template": "CLOUD_REVIEW"}).json()
    client.put(f"/api/graphs/{g['id']}", headers=arch, json={"draft": g["draft"]})
    client.post(f"/api/graphs/{g['id']}/publish", headers=arch)
    run = client.post("/api/runs", headers=ps, json={"graph_id": g["id"], "project_id": proj["id"], "version": 1}).json()
    r = client.get(f"/api/runs/{run['id']}", headers=ps).json()
    assert r["status"] == "awaiting_approval", r
    return r


def test_bridge_requires_token(client):
    assert client.post("/internal/n8n/step", json={"run_id": "x", "node_id": "y"}).status_code == 401
    assert client.post("/internal/n8n/step", headers={"X-Aivanta-Bridge-Token": "wrong"}, json={"run_id": "x"}).status_code == 401
    assert client.get("/gateway/v1/models", headers={"Authorization": f"Bearer {TOKEN['X-Aivanta-Bridge-Token']}"}).status_code == 200


def test_bridge_steps_are_idempotent_and_runs_are_n8n(client):
    r = _paused_run(client)
    assert r["runtime"] == "n8n"
    done = next(nid for nid, s in r["node_status"].items() if s == "succeeded" and nid != "start")
    res = client.post("/internal/n8n/step", headers=TOKEN, json={"run_id": r["id"], "node_id": done, "execution_id": "x"})
    assert res.status_code == 200 and res.json()["cached"] is True
    assert client.post("/internal/n8n/nope", headers=TOKEN, json={"run_id": r["id"], "node_id": done}).status_code == 422
    assert client.post("/internal/n8n/step", headers=TOKEN, json={"run_id": "missing", "node_id": done}).status_code == 404


def test_model_gateway_speaks_openai(client):
    r = _paused_run(client)
    agent = "tech"   # Technology Advisor agent of the Cloud Cost Review template
    body = {"model": f"aivanta:{r['id']}:{agent}", "messages": [{"role": "system", "content": "Return JSON"}, {"role": "user", "content": "go"}]}
    res = client.post("/gateway/v1/chat/completions", headers={"Authorization": f"Bearer {TOKEN['X-Aivanta-Bridge-Token']}"}, json=body)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["object"] == "chat.completion" and data["choices"][0]["message"]["content"].startswith("{")
    bad = client.post("/gateway/v1/chat/completions", headers=TOKEN, json={**body, "model": "gpt-4o"})
    assert bad.status_code == 422
