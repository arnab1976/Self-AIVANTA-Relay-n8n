"""Cloud cost scenarios from a versioned price snapshot.

The bundled snapshot holds ILLUSTRATIVE unit prices so the platform runs out
of the box. In production, load snapshots from the AWS, Azure and GCP
official pricing sources (see aivanta_connectors cloud_pricing) and keep the
effective date with every estimate.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

D = Decimal
SNAPSHOT_PATH = Path(__file__).parent / "catalog" / "price_snapshot.json"
STORAGE_CLASS = {"Standard": D("1"), "Infrequent access": D("0.55"), "Archive": D("0.2")}
COMMITMENT = {"none": D("0"), "1y": D("0.20"), "3y": D("0.35")}
SCENARIO_MULT = {"low": D("0.8"), "base": D("1"), "high": D("1.3")}


def load_snapshot(path: Path | None = None) -> dict:
    return json.loads((path or SNAPSHOT_PATH).read_text(encoding="utf-8"))


def snapshot_age_days(snapshot: dict, today: date | None = None) -> int:
    eff = date.fromisoformat(snapshot["effective_date"])
    return ((today or date.today()) - eff).days


def monthly_cost(workload: dict, provider: str, snapshot: dict, fx_rate: Decimal = D(1), multiplier: Decimal = D(1)) -> dict:
    p = snapshot["providers"][provider]
    u = {k: D(str(v)) for k, v in p["unit_prices_usd"].items()}
    region = D(str(snapshot["region_multipliers"].get(workload.get("region", ""), 1)))
    envs = int(workload.get("environments", 1))
    env_factor = D(1) + D("0.4") * max(0, envs - 1)
    commit = COMMITMENT.get(str(workload.get("commitment", "none")), D(0))
    w = {k: D(str(workload.get(k, 0))) for k in ("vcpu", "instance_count", "runtime_hours", "storage_gb", "requests_millions",
                                                 "llm_tokens_millions", "egress_gb", "observability_gb")}
    parts = {
        "compute": w["vcpu"] * w["instance_count"] * w["runtime_hours"] * u["vcpu_hour"] * region * env_factor * (D(1) - commit),
        "storage": w["storage_gb"] * u["storage_gb_month"] * STORAGE_CLASS.get(workload.get("storage_class", "Standard"), D(1)) * D("1.25") * region * env_factor,
        "requests": w["requests_millions"] * u["requests_per_million"],
        "llm_tokens": w["llm_tokens_millions"] * u["llm_tokens_per_million"],
        "egress": w["egress_gb"] * u["egress_gb"],
        "observability": w["observability_gb"] * u["observability_gb"] * env_factor,
    }
    parts = {k: v * multiplier for k, v in parts.items()}
    parts["support"] = sum(parts.values(), D(0)) * D(str(p["support_pct"]))
    parts = {k: (v * fx_rate).quantize(D("0.01")) for k, v in parts.items()}
    return {"provider": provider, "name": p["name"], "stack": p["stack"], "parts": {k: str(v) for k, v in parts.items()},
            "monthly": str(sum(parts.values(), D(0)).quantize(D("0.01")))}


def compare(workload: dict, snapshot: dict | None = None, fx_rate: Decimal = D(1), currency: str = "USD") -> dict:
    snap = snapshot or load_snapshot()
    out = {}
    for prov in snap["providers"]:
        out[prov] = {s: monthly_cost(workload, prov, snap, fx_rate, m) for s, m in SCENARIO_MULT.items()}
    return {"currency": currency, "snapshot_effective_date": snap["effective_date"], "snapshot_id": snap["snapshot_id"],
            "snapshot_age_days": snapshot_age_days(snap), "illustrative": snap.get("illustrative", True), "providers": out}
