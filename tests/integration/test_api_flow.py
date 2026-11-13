"""End-to-end API tests (mock LLM). They exercise the Definition of Done through
HTTP exactly as the web app does. Identical in both editions."""
from __future__ import annotations

import io

from fastapi.testclient import TestClient


def login(client: TestClient, tenant="FP", role="presales", name=None) -> dict:
    r = client.post("/api/auth/dev-login", json={"tenant_code": tenant, "role": role, "name": name or f"{role.title()} Tester"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def first(client, path, headers, **match):
    rows = client.get(path, headers=headers).json()
    return next(r for r in rows if all(r.get(k) == v for k, v in match.items()))


def test_meta_and_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    meta = client.get("/api/meta").json()
    assert meta["runtime"] == "n8n"


def test_full_rfp_to_sow_flow(client):
    ps = login(client, role="presales", name="Priya Presales")
    arch = login(client, role="architect", name="Ananya Architect")
    fin = login(client, role="finance", name="Farhan Finance")
    rev = login(client, role="reviewer", name="Ritu Reviewer")

    # project + RFP upload (malware scan + PII redaction)
    proj = client.post("/api/projects", headers=ps, json={"client": "Kestrel Bank", "name": "Digital Lending", "industry": "BFSI",
                                                          "scope": "Digital lending platform"}).json()
    rfp = b"3.1 The platform shall capture loan applications online. 6.1 The system must respond within 2 seconds. Contact: jane.doe@kestrel.example or +91 98765 43210."
    up = client.post(f"/api/projects/{proj['id']}/rfp", headers=ps, files={"file": ("RFP_Kestrel.txt", io.BytesIO(rfp), "text/plain")})
    assert up.status_code == 201, up.text
    assert up.json()["pii_redactions"].get("email") == 1
    bad = client.post(f"/api/projects/{proj['id']}/rfp", headers=ps, files={"file": ("evil.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")})
    assert bad.status_code == 422
    client.patch(f"/api/projects/{proj['id']}", headers=ps, json={"clarifications": [{"question": "Is migration in scope?", "open": True}]})

    # canvas: create from template, invalid edge rejected, save, publish
    g = client.post("/api/graphs", headers=arch, json={"name": "Kestrel RFP-to-SOW", "template": "RFP_SOW"}).json()
    assert client.post(f"/api/graphs/{g['id']}/edge-check", headers=arch, json={"source": "rfp", "target": "start"}).json()["ok"] is False
    saved = client.put(f"/api/graphs/{g['id']}", headers=arch, json={"draft": g["draft"]}).json()
    assert saved["validation"]["ok"] is True
    assert client.post(f"/api/graphs/{g['id']}/publish", headers=ps).status_code == 403          # presales cannot publish
    pub = client.post(f"/api/graphs/{g['id']}/publish", headers=arch)
    assert pub.status_code == 201 and pub.json()["version"] == 1
    assert client.post(f"/api/graphs/{g['id']}/publish", headers=arch).status_code == 409         # unchanged draft

    # run the published version; it pauses at the clarification gate
    run = client.post("/api/runs", headers=ps, json={"graph_id": g["id"], "project_id": proj["id"], "version": 1}).json()
    r = client.get(f"/api/runs/{run['id']}", headers=ps).json()
    assert r["status"] == "awaiting_approval", r
    assert r["outputs"]["rfp"]["requirements"][0]["source"]["document"] == "RFP_Kestrel.txt"

    def pending(headers, role):
        return [a for a in client.get("/api/approvals?status=Pending", headers=headers).json() if a["run_id"] == run["id"] and a["approver_role"] == role]

    clar = pending(ps, "presales")[0]
    assert client.post(f"/api/approvals/{clar['id']}/decide", headers=fin, json={"decision": "Approved"}).status_code == 403  # wrong role
    assert client.post(f"/api/approvals/{clar['id']}/decide", headers=ps, json={"decision": "Approved", "comment": "Client confirmed"}).status_code == 200
    assert client.get(f"/api/runs/{run['id']}", headers=ps).json()["status"] == "awaiting_approval"

    capp = pending(fin, "finance")[0]
    assert capp["kind"] == "Commercial Approval"
    assert client.post(f"/api/approvals/{capp['id']}/decide", headers=fin, json={"decision": "Approved"}).status_code == 200
    final = pending(rev, "reviewer")[0]
    assert client.post(f"/api/approvals/{final['id']}/decide", headers=rev, json={"decision": "Approved"}).status_code == 200
    done = client.get(f"/api/runs/{run['id']}", headers=ps).json()
    assert done["status"] == "succeeded", done
    assert done["node_status"]["end"] == "succeeded"

    # artifacts + exports carry version, review status, assumptions and sources
    arts = client.get(f"/api/artifacts?project_id={proj['id']}", headers=rev).json()
    kinds = {a["type"] for a in arts}
    assert {"Compliance matrix", "BRD", "SOW", "Pricing worksheet"} <= kinds
    sow = next(a for a in arts if a["type"] == "SOW")
    for fmt, magic in (("docx", b"PK"), ("pdf", b"%PDF"), ("xlsx", b"PK")):
        resp = client.get(f"/api/artifacts/{sow['id']}/export?format={fmt}", headers=rev)
        assert resp.status_code == 200 and resp.content[:4].startswith(magic)

    # promotion to prod requires a succeeded run (now satisfied) and EA/admin
    ea = login(client, role="ea", name="Esha EA")
    assert client.post(f"/api/graphs/{g['id']}/versions/1/promote", headers=ea).json()["environment"] == "staging"
    assert client.post(f"/api/graphs/{g['id']}/versions/1/promote", headers=ea).json()["environment"] == "prod"

    # audit chain intact
    audit = client.get("/api/audit", headers=ea).json()
    assert audit["chain"]["valid"] is True


def test_pricing_engine_endpoint_and_discount_exception(client):
    fin = login(client, role="finance", name="Fiona Finance")
    ex = client.get("/api/pricing/blueprint-example", headers=fin).json()
    assert ex["labor"] == "5400000.00" and ex["delivery_cost"] == "7000000.00" and ex["selling_price"] == "10000000.00"
    proj = first(client, "/api/projects", fin, code="PRJ-1042")
    res = client.post(f"/api/projects/{proj['id']}/estimates", headers=fin, json={"inputs": {"discount_pct": 15}}).json()
    assert any(f["code"] == "discount_exception" for f in res["flags"])
    assert set(res["scenarios"]) == {"low", "base", "high"}
    kinds = [a["kind"] for a in client.get("/api/approvals?status=Pending", headers=fin).json()]
    assert "Discount exception" in kinds


def test_tenant_isolation(client):
    fp = login(client, tenant="FP", role="presales")
    us = login(client, tenant="US", role="presales")
    fp_proj = client.get("/api/projects", headers=fp).json()[0]
    assert client.get(f"/api/projects/{fp_proj['id']}", headers=us).status_code == 404
    assert all(p["id"] != fp_proj["id"] for p in client.get("/api/projects", headers=us).json())
    fp_graph = client.get("/api/graphs", headers=fp).json()[0]
    assert client.get(f"/api/graphs/{fp_graph['id']}", headers=us).status_code == 404


def test_model_allowlist_blocks_publish(client):
    adm = login(client, tenant="HX", role="admin", name="Hari Admin")
    arch = login(client, tenant="HX", role="architect", name="Hema Architect")
    g = client.post("/api/graphs", headers=arch, json={"name": "Cloud check", "template": "CLOUD_REVIEW"}).json()
    # HX does not allow enterprise-reasoning; CLOUD_REVIEW agents default to enterprise-fast, so make one non-compliant
    draft = g["draft"]
    next(n for n in draft["nodes"] if n["type"] == "agent")["config"]["model_profile"] = "enterprise-reasoning"
    client.put(f"/api/graphs/{g['id']}", headers=arch, json={"draft": draft})
    r = client.post(f"/api/graphs/{g['id']}/publish", headers=arch)
    assert r.status_code == 422 and "model_not_allowed" in str(r.json())
    client.patch("/api/tenants/current", headers=adm, json={"allowed_models": ["enterprise-reasoning", "enterprise-fast", "local-open-weight"]})
    assert client.post(f"/api/graphs/{g['id']}/publish", headers=arch).status_code == 201


def test_uat_endpoint(client):
    ps = login(client, role="presales")
    checks = client.get("/api/governance/uat", headers=ps).json()
    assert len(checks) == 7 and {c["id"] for c in checks} >= {"rfp_to_sow_e2e", "export_fidelity"}
