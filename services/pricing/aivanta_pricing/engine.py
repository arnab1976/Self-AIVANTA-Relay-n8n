"""Deterministic pricing engine (blueprint section 12).

person-months   = FTE x months
resource cost   = sum(person-months x fully-loaded monthly rate)
delivery cost   = labor + cloud + licenses + travel + overhead + contingency
selling price   = delivery cost / (1 - target gross margin)

Decimal arithmetic, versioned rate card / FX inputs and explicit flags.
No LLM ever produces these numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

D = Decimal
CENT = D("0.01")


def _d(v) -> Decimal:
    return v if isinstance(v, Decimal) else D(str(v))


def money(v: Decimal) -> Decimal:
    return v.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class RoleLine:
    role: str
    fte: Decimal
    months: Decimal
    monthly_rate: Decimal

    @property
    def person_months(self) -> Decimal:
        return _d(self.fte) * _d(self.months)

    @property
    def cost(self) -> Decimal:
        return self.person_months * _d(self.monthly_rate)


@dataclass
class PricingInput:
    role_lines: list[RoleLine]
    cloud_monthly: Decimal = D(0)
    duration_months: Decimal | None = None
    licenses: Decimal = D(0)
    travel: Decimal = D(0)
    other_costs: Decimal = D(0)
    overhead_pct: Decimal = D(0)
    contingency_pct: Decimal = D(0)
    target_margin_pct: Decimal = D(30)
    discount_pct: Decimal = D(0)
    currency: str = "INR"
    rate_card_version: str = "unversioned"
    fx_version: str = "n/a"

    @classmethod
    def from_dict(cls, data: dict, rate_card: dict[str, float] | None = None) -> "PricingInput":
        rc = rate_card or {}
        lines = []
        for ln in data.get("role_lines", []):
            rate = ln.get("monthly_rate")
            if rate is None:
                if ln["role"] not in rc:
                    raise ValueError(f"Role '{ln['role']}' is not on rate card {data.get('rate_card_version', '')}")
                rate = rc[ln["role"]]
            lines.append(RoleLine(ln["role"], _d(ln.get("fte", 0)), _d(ln.get("months", 0)), _d(rate)))
        kw = {k: _d(data[k]) for k in ("cloud_monthly", "duration_months", "licenses", "travel", "other_costs", "overhead_pct",
                                        "contingency_pct", "target_margin_pct", "discount_pct") if data.get(k) is not None}
        return cls(role_lines=lines, currency=data.get("currency", "INR"), rate_card_version=data.get("rate_card_version", "unversioned"),
                   fx_version=data.get("fx_version", "n/a"), **kw)


@dataclass
class PricingResult:
    currency: str
    person_months: Decimal
    duration_months: Decimal
    labor: Decimal
    cloud: Decimal
    licenses: Decimal
    travel: Decimal
    other_costs: Decimal
    overhead: Decimal
    contingency: Decimal
    delivery_cost: Decimal
    list_price: Decimal
    selling_price: Decimal
    effective_margin_pct: Decimal
    lines: list[dict] = field(default_factory=list)
    reconciled: bool = True
    rate_card_version: str = ""
    fx_version: str = ""

    def to_dict(self) -> dict:
        out = {}
        for k, v in self.__dict__.items():
            out[k] = str(v) if isinstance(v, Decimal) else v
        return out


def compute(inp: PricingInput, effort_multiplier: Decimal = D(1), cloud_multiplier: Decimal = D(1)) -> PricingResult:
    if not D(0) <= inp.target_margin_pct < D(100):
        raise ValueError("Target margin must be between 0 and 100 (exclusive).")
    lines, pm, labor = [], D(0), D(0)
    for ln in inp.role_lines:
        lpm = ln.person_months * effort_multiplier
        lcost = lpm * ln.monthly_rate
        pm += lpm
        labor += lcost
        lines.append({"role": ln.role, "fte": str(ln.fte), "months": str(ln.months), "person_months": str(lpm),
                      "monthly_rate": str(ln.monthly_rate), "cost": str(money(lcost))})
    duration = inp.duration_months if inp.duration_months is not None else max([ln.months for ln in inp.role_lines], default=D(0))
    cloud = inp.cloud_monthly * duration * cloud_multiplier
    base = labor + cloud + inp.licenses + inp.travel + inp.other_costs
    overhead = base * inp.overhead_pct / D(100)
    contingency = (base + overhead) * inp.contingency_pct / D(100)
    delivery = base + overhead + contingency
    list_price = delivery / (D(1) - inp.target_margin_pct / D(100))
    selling = list_price * (D(1) - inp.discount_pct / D(100))
    eff = (D(1) - delivery / selling) * D(100) if selling else D(0)
    # Rounded line costs must add up to the labor total within rounding tolerance (one cent per line).
    reconciled = abs(sum((_d(x["cost"]) for x in lines), D(0)) - money(labor)) <= CENT * max(1, len(lines))
    return PricingResult(currency=inp.currency, person_months=pm, duration_months=duration, labor=money(labor), cloud=money(cloud),
                         licenses=money(inp.licenses), travel=money(inp.travel), other_costs=money(inp.other_costs),
                         overhead=money(overhead), contingency=money(contingency), delivery_cost=money(delivery),
                         list_price=money(list_price), selling_price=money(selling), effective_margin_pct=eff.quantize(D("0.01")),
                         lines=lines, reconciled=reconciled, rate_card_version=inp.rate_card_version, fx_version=inp.fx_version)


SCENARIOS = {"low": (D("0.90"), D("0.80")), "base": (D("1"), D("1")), "high": (D("1.15"), D("1.30"))}


def scenarios(inp: PricingInput) -> dict[str, PricingResult]:
    """Low / base / high: effort -10%/+15%, cloud -20%/+30%."""
    return {k: compute(inp, e, c) for k, (e, c) in SCENARIOS.items()}


@dataclass
class PricingPolicy:
    margin_floor_pct: Decimal = D(22)
    discount_limit_pct: Decimal = D(10)
    price_snapshot_age_days: int = 0
    max_snapshot_age_days: int = 30


def check(inp: PricingInput, result: PricingResult, policy: PricingPolicy) -> list[dict]:
    """Flags for invalid or negative inputs, unapproved discounts, margin breaches and stale cloud prices."""
    flags: list[dict] = []
    nums: Iterable[tuple[str, Decimal]] = [("cloud_monthly", inp.cloud_monthly), ("licenses", inp.licenses), ("travel", inp.travel),
                                           ("overhead_pct", inp.overhead_pct), ("contingency_pct", inp.contingency_pct),
                                           ("discount_pct", inp.discount_pct)]
    for name, v in nums:
        if v < 0:
            flags.append({"severity": "blocker", "code": "negative_input", "message": f"{name} cannot be negative."})
    for ln in inp.role_lines:
        if ln.fte < 0 or ln.months < 0 or ln.monthly_rate < 0:
            flags.append({"severity": "blocker", "code": "negative_input", "message": f"Role line '{ln.role}' has a negative value."})
    if inp.discount_pct > policy.discount_limit_pct:
        flags.append({"severity": "blocker", "code": "discount_exception",
                      "message": f"Discount {inp.discount_pct}% exceeds the approved limit of {policy.discount_limit_pct}%; a discount exception approval is required."})
    if result.effective_margin_pct < policy.margin_floor_pct:
        flags.append({"severity": "blocker", "code": "margin_breach",
                      "message": f"Effective margin {result.effective_margin_pct}% is below the {policy.margin_floor_pct}% floor."})
    if policy.price_snapshot_age_days > policy.max_snapshot_age_days:
        flags.append({"severity": "warning", "code": "stale_cloud_prices",
                      "message": f"Cloud price snapshot is {policy.price_snapshot_age_days} days old; refresh before submission."})
    if not result.reconciled:
        flags.append({"severity": "blocker", "code": "not_reconciled", "message": "Role lines do not reconcile to the labor total."})
    return flags


def blueprint_example() -> PricingResult:
    """Worked example from the blueprint: 30 PM x INR 1,80,000 + INR 16,00,000 at 30% margin = INR 1,00,00,000."""
    inp = PricingInput(role_lines=[RoleLine("Blended team", D(30), D(1), D(180000))], other_costs=D(1600000),
                       target_margin_pct=D(30), duration_months=D(1), currency="INR", rate_card_version="blueprint-example")
    return compute(inp)
