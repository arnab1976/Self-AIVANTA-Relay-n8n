"""One-time n8n bootstrap for AIVANTA Relay.

    python scripts/n8n_bootstrap.py --n8n http://localhost:5678 --email ops@example.com --password '<strong password>' [--write-env .env]

1. Creates the n8n owner account on a fresh instance (skipped if one exists).
2. Signs in and creates a public-API key labelled "AIVANTA Relay".
3. Prints N8N_API_KEY (and writes it into the env file with --write-env).

The API then creates the two n8n credentials it needs (AIVANTA Bridge and AIVANTA
Model Gateway) on startup. This script uses n8n's internal REST endpoints
(`/rest/owner/setup`, `/rest/login`, `/rest/api-keys`), which can change between
n8n versions; if it fails, create the owner and the API key in the n8n UI
(Settings → n8n API) and set N8N_API_KEY by hand.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import httpx

API_SCOPES = ["workflow:create", "workflow:read", "workflow:update", "workflow:delete", "workflow:list", "workflow:activate", "workflow:deactivate",
              "workflow:move", "workflowTags:update", "workflowTags:list", "tag:create", "tag:read", "tag:list", "tag:update",
              "credential:create", "credential:delete", "credential:move", "execution:read", "execution:list", "execution:retry", "execution:delete"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n8n", default="http://localhost:5678")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--first-name", default="AIVANTA")
    ap.add_argument("--last-name", default="Operations")
    ap.add_argument("--write-env", default=None, help="env file to update with N8N_API_KEY")
    a = ap.parse_args()
    base = a.n8n.rstrip("/")
    with httpx.Client(base_url=base, timeout=30, follow_redirects=True) as c:
        r = c.post("/rest/owner/setup", json={"email": a.email, "firstName": a.first_name, "lastName": a.last_name, "password": a.password})
        if r.status_code < 400:
            print("owner account created")
        else:
            print(f"owner setup skipped ({r.status_code}): an owner probably exists already")
        r = c.post("/rest/login", json={"emailOrLdapLoginId": a.email, "email": a.email, "password": a.password})
        if r.status_code >= 400:
            print(f"login failed: {r.status_code} {r.text[:300]}", file=sys.stderr)
            return 1
        body = {"label": "AIVANTA Relay", "expiresAt": None, "scopes": API_SCOPES}
        r = c.post("/rest/api-keys", json=body)
        if r.status_code >= 400:   # older n8n versions take no body
            r = c.post("/rest/api-keys")
        if r.status_code >= 400:
            print(f"API key creation failed: {r.status_code} {r.text[:300]}", file=sys.stderr)
            return 1
        data = r.json().get("data", r.json())
        key = data.get("rawApiKey") or data.get("apiKey")
        if not key:
            print(f"Unexpected response: {data}", file=sys.stderr)
            return 1
    print(f"N8N_API_KEY={key}")
    if a.write_env:
        p = Path(a.write_env)
        txt = p.read_text() if p.exists() else ""
        txt = re.sub(r"^N8N_API_KEY=.*$", f"N8N_API_KEY={key}", txt, flags=re.M) if "N8N_API_KEY=" in txt else txt + f"\nN8N_API_KEY={key}\n"
        p.write_text(txt)
        print(f"updated {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
