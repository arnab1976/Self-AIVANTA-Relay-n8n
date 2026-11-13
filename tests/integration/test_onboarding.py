"""Request Access → Tenant Admin / Provider Admin approval → provisioning, plans and suspension."""
from __future__ import annotations

def login(client, tenant="FP", role="presales", name=None) -> dict:
    r = client.post("/api/auth/dev-login", json={"tenant_code": tenant, "role": role, "name": name or f"{role.title()} Tester"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}



def provider(client):
    r = client.post("/api/provider/dev-login", json={"name": "Platform Ops"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_join_request_is_approved_by_tenant_admin(client):
    assert client.get("/api/public/plans").json()["plans"]["Enterprise"]["n8n"] == "dedicated"
    r = client.post("/api/access-requests", json={"kind": "join", "name": "Asha Rao", "email": "asha.rao@fp.example", "organisation": "Feuji",
                                                  "tenant_code": "FP", "role": "finance"})
    assert r.status_code == 201 and r.json()["routed_to"] == "Tenant Admin"
    ps = login(client, role="presales")
    assert client.get("/api/access-requests", headers=ps).status_code == 403          # only the tenant admin
    admin = login(client, role="admin", name="Arnav Admin")
    rid = next(x["id"] for x in client.get("/api/access-requests?status=Pending", headers=admin).json() if x["email"] == "asha.rao@fp.example")
    assert client.post(f"/api/access-requests/{rid}/decide", headers=admin, json={"decision": "Approved"}).json()["status"] == "Approved"
    users = client.get("/api/tenant-admin/users", headers=admin).json()
    assert any(u["email"] == "asha.rao@fp.example" and u["roles"] == ["finance"] for u in users)


def test_new_org_is_provisioned_by_provider_and_can_be_suspended(client):
    r = client.post("/api/access-requests", json={"kind": "new_org", "name": "Ravi Iyer", "email": "ravi@orion.example", "organisation": "Orion Tech",
                                                  "plan": "Enterprise", "cloud": "Azure", "region": "EU (Frankfurt)", "currency": "USD"})
    assert r.status_code == 201 and r.json()["routed_to"] == "Provider Admin"
    pv = provider(client)
    assert client.get("/api/provider/overview", headers=login(client)).status_code == 403   # tenant users are not providers
    rid = next(x["id"] for x in client.get("/api/provider/requests?status=Pending", headers=pv).json() if x["email"] == "ravi@orion.example")
    out = client.post(f"/api/provider/requests/{rid}/decide", headers=pv, json={"decision": "Approved"}).json()
    t = out["tenant"]
    assert t["plan"] == "Enterprise" and t["cloud"] == "Azure" and t["n8n_placement"] == "dedicated" and t["isolation_model"] == "dedicated-database"
    # the new tenant works, with its own canvas and project
    hdr = login(client, tenant=t["code"], role="architect")
    assert client.get("/api/graphs", headers=hdr).json()
    # suspend → blocked; reactivate → allowed
    client.patch(f"/api/provider/tenants/{t['id']}", headers=pv, json={"status": "Suspended"})
    assert client.get("/api/projects", headers=hdr).status_code == 403
    client.patch(f"/api/provider/tenants/{t['id']}", headers=pv, json={"status": "Active", "plan": "Growth"})
    assert client.get("/api/projects", headers=hdr).status_code == 200
    row = next(x for x in client.get("/api/provider/overview", headers=pv).json()["tenants"] if x["id"] == t["id"])
    assert row["plan"] == "Growth" and row["n8n_placement"] == "shared"
