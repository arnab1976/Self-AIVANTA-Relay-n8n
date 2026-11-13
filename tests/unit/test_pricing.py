from datetime import date, timedelta
from decimal import Decimal as D

from aivanta_pricing import PricingInput, PricingPolicy, RoleLine, blueprint_example, check, compute, scenarios
from aivanta_pricing import cloud


def test_blueprint_worked_example():
    r = blueprint_example()
    assert r.person_months == D(30)
    assert r.labor == D("5400000.00")
    assert r.delivery_cost == D("7000000.00")
    assert r.selling_price == D("10000000.00")
    assert r.effective_margin_pct == D("30.00")


def _inp(**kw):
    base = dict(role_lines=[RoleLine("Architect", D("0.5"), D(3), D(320000)), RoleLine("Engineer", D(2), D(3), D(170000))],
                cloud_monthly=D(50000), overhead_pct=D(8), contingency_pct=D(10), target_margin_pct=D(30))
    base.update(kw)
    return PricingInput(**base)


def test_formula_chain_and_reconciliation():
    r = compute(_inp())
    labor = D("1.5") * 320000 + D(6) * 170000
    assert r.labor == labor and r.reconciled
    base = labor + D(50000) * 3
    delivery = (base * D("1.08")) * D("1.10")
    assert abs(r.delivery_cost - delivery) < D("0.01")
    assert abs(r.selling_price - delivery / D("0.7")) < D("0.01")


def test_scenarios_order():
    s = scenarios(_inp())
    assert s["low"].selling_price < s["base"].selling_price < s["high"].selling_price


def test_flags():
    inp = _inp(discount_pct=D(15), licenses=D(-1))
    r = compute(inp)
    codes = {f["code"] for f in check(inp, r, PricingPolicy(price_snapshot_age_days=45))}
    assert {"discount_exception", "negative_input", "stale_cloud_prices", "margin_breach"} <= codes


def test_rate_card_lookup_rejects_unknown_role():
    import pytest
    with pytest.raises(ValueError):
        PricingInput.from_dict({"role_lines": [{"role": "Wizard", "fte": 1, "months": 1}]}, {"Architect": 1})


def test_cloud_compare_and_staleness():
    snap = cloud.load_snapshot()
    w = {"region": "India (Mumbai)", "vcpu": 8, "instance_count": 3, "runtime_hours": 730, "storage_gb": 500, "requests_millions": 20,
         "llm_tokens_millions": 40, "egress_gb": 200, "observability_gb": 50, "environments": 3, "commitment": "none"}
    res = cloud.compare(w, snap)
    for prov in ("aws", "gcp", "azure"):
        lo, base, hi = (D(res["providers"][prov][s]["monthly"]) for s in ("low", "base", "high"))
        assert lo < base < hi
    committed = cloud.monthly_cost({**w, "commitment": "3y"}, "aws", snap)
    assert D(committed["parts"]["compute"]) < D(res["providers"]["aws"]["base"]["parts"]["compute"])
    assert cloud.snapshot_age_days(snap, date.fromisoformat(snap["effective_date"]) + timedelta(days=40)) == 40
