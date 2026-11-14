"""Sensitivity ("tornado") analysis: which assumptions move minimum cash the most (issue #78).

For each docs/MATH_MODEL.md §10 assumption, re-run ``core.financials.simulate`` with that one input moved down and
up (everything else held at its value) and report min_t C_t on each side, the week it occurs, and the swing

    swing = | minCash(+) - minCash(-) |

Entries are sorted by swing, largest first. This module adds no formula: every number comes from ``simulate()``.
The output is SIMULATED (a deterministic engine run on the SYNTHETIC demo business), not a forecast.

Choices (documented so a finance reviewer can disagree with them):
- Step: relative, x(1 - rel) and x(1 + rel), default rel = 0.10. Series inputs (a list of weekly values) scale
  every week by the same factor.
- Store sales: all stores move together (total S^base scales by 1 ± rel), as one driver.
- Supplier lag L_p is a whole number of weeks, so it moves by -1 / +1 week instead of ±rel. ``prior_purchases``
  must list exactly L_p pre-horizon values: a shorter lag keeps the most recent ones (P_0 last); a longer lag
  prepends copies of the oldest known value (the §10 steady-state assumption P_{-1} = P_0).
- φ (outage share) lives on the scenario's supplier outage. With no outage in the scenario it is NOT_APPLICABLE.
- NOT_APPLICABLE also marks inputs that cannot move min cash in this run (issue #115), so a 0.00 swing is never read
  as "this doesn't matter": B-bar always (only the optimizer reads it); π and F_b when the plan does not use the backup
  supplier (x_b = 0); s_R when the revolver is never drawn (B_0 = 0 and no draws in the plan); and any input equal
  to 0, which a relative step cannot move.
- Each computable entry also reports max_abs_delta = max(|delta low|, |delta high|), next to the swing.
- Opening balances (C_0, S_0, prior purchases, I_0, D_1, B_0) are not perturbed: they are balances known at the
  start of the plan, not forward-looking assumptions. C_min and I_min are not perturbed either: they are optimizer
  floors (§4) that simulate() does not use. Per-case placeholders (K_t, E_t, X_t, A_t) are zero in the demo business.
- Pre-horizon values stay fixed when g or S^base moves (P_{-1}, P_0 and S_0 already happened).
- A perturbed value the model rejects (e.g. a fraction above 1) or a run that simulate() refuses is reported as
  INFEASIBLE with the reason, never dropped. Such an entry has no swing and sorts after every computable entry.
- Swings equal to within 10^-6 dollars are ties; ties keep the fixed driver order below.

Pure: inputs are never mutated (each run gets a re-validated copy). No I/O, no randomness, no clock.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from core.financials import ActionPlan, BusinessParams, ScenarioShock, Series, simulate

Value = float | list[float]

# Swings that agree to this many decimals (dollars) count as ties for sorting.
SWING_TIE_DECIMALS = 6


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class SensitivityPoint(_Model):
    """One perturbed run: the input value used and the min cash that simulate() returned for it."""

    value: Value | None  # the perturbed input (None if it could not be formed)
    status: Literal["OK", "INFEASIBLE"]
    min_cash: float | None  # min_t C_t, t = 1..T
    min_cash_week: int | None  # first week attaining it
    delta_vs_base: float | None  # min_cash - base min cash
    reason: str | None = None  # why the run is INFEASIBLE


class TornadoEntry(_Model):
    key: str
    label: str
    symbol: str
    step: str  # how the input was moved, e.g. "-10% / +10%" or "-1 / +1 week"
    base_value: Value | None
    status: Literal["OK", "INFEASIBLE", "NOT_APPLICABLE"]
    low: SensitivityPoint | None  # input moved down
    high: SensitivityPoint | None  # input moved up
    swing: float | None  # |high.min_cash - low.min_cash|; None unless both sides are OK
    max_abs_delta: float | None = None  # max(|low.delta_vs_base|, |high.delta_vs_base|); None unless both sides OK
    note: str | None = None


class TornadoResult(_Model):
    provenance: Literal["SIMULATED"] = "SIMULATED"
    scenario_name: str
    rel: float
    base_min_cash: float
    base_min_cash_week: int
    entries: list[TornadoEntry]  # sorted by swing, largest first


# --------------------------------------------------------------------------- drivers

Inputs = tuple[BusinessParams, ScenarioShock]


@dataclass(frozen=True)
class _Driver:
    key: str
    label: str
    symbol: str
    base: Callable[[BusinessParams, ScenarioShock], Value | None]
    # (params, shock, direction -1/+1, rel) -> the perturbed input value
    moved: Callable[[BusinessParams, ScenarioShock, int, float], Value]
    # (params, shock, direction, rel) -> validated perturbed inputs; raises ValueError if the model rejects them
    build: Callable[[BusinessParams, ScenarioShock, int, float], Inputs]
    integer_step: bool = False
    note: str | None = None
    # (params, shock, plan) -> why the driver cannot move min cash in this run, or None
    not_applicable: Callable[[BusinessParams, ScenarioShock, ActionPlan], str | None] = lambda p, s, a: None


def _scale(value: Series, factor: float) -> Value:
    return [float(v) * factor for v in value] if isinstance(value, list) else float(value) * factor


def _is_zero(value: Value) -> bool:
    return all(v == 0.0 for v in value) if isinstance(value, list) else value == 0.0


def _rebuild(params: BusinessParams, **update) -> BusinessParams:
    """A validated copy of ``params`` with ``update`` applied; raises ValueError if the model rejects it."""
    data = params.model_dump()
    data.update(update)
    return BusinessParams.model_validate(data)


PlanCheck = Callable[[BusinessParams, ScenarioShock, ActionPlan], str | None]


def _field_driver(field: str, label: str, symbol: str, note: str | None = None,
                  unused_when: PlanCheck | None = None) -> _Driver:
    def base(params: BusinessParams, shock: ScenarioShock) -> Value:
        return _scale(getattr(params, field), 1.0)

    def moved(params: BusinessParams, shock: ScenarioShock, d: int, rel: float) -> Value:
        return _scale(getattr(params, field), 1.0 + d * rel)

    def build(params: BusinessParams, shock: ScenarioShock, d: int, rel: float) -> Inputs:
        return _rebuild(params, **{field: moved(params, shock, d, rel)}), shock

    def not_applicable(params: BusinessParams, shock: ScenarioShock, plan: ActionPlan) -> str | None:
        if unused_when is not None and (why := unused_when(params, shock, plan)) is not None:
            return why
        if _is_zero(_scale(getattr(params, field), 1.0)):
            return f"{symbol} is 0, so a relative step does not move it"
        return None

    return _Driver(field, label, symbol, base, moved, build, note=note, not_applicable=not_applicable)


def _total_sales(store_sales: list[Value], horizon: int) -> Value:
    """Σ_ℓ S^base_ℓ: one number if every store is a constant, else the weekly totals."""
    if not any(isinstance(s, list) for s in store_sales):
        return sum(store_sales)  # type: ignore[arg-type]
    weekly = [s if isinstance(s, list) else [s] * horizon for s in store_sales]
    return [sum(week) for week in zip(*weekly, strict=True)]


def _sales_base(params: BusinessParams, shock: ScenarioShock) -> Value:
    return _total_sales([_scale(s.base_sales, 1.0) for s in params.stores], params.horizon_weeks)


def _sales_moved(params: BusinessParams, shock: ScenarioShock, d: int, rel: float) -> Value:
    return _total_sales([_scale(s.base_sales, 1.0 + d * rel) for s in params.stores], params.horizon_weeks)


def _sales_build(params: BusinessParams, shock: ScenarioShock, d: int, rel: float) -> Inputs:
    stores = [{"name": s.name, "base_sales": _scale(s.base_sales, 1.0 + d * rel)} for s in params.stores]
    return _rebuild(params, stores=stores), shock


def _lag_base(params: BusinessParams, shock: ScenarioShock) -> Value:
    return float(params.supplier_lag_weeks)


def _lag_moved(params: BusinessParams, shock: ScenarioShock, d: int, rel: float) -> Value:
    return float(params.supplier_lag_weeks + d)


def _lag_build(params: BusinessParams, shock: ScenarioShock, d: int, rel: float) -> Inputs:
    lag = params.supplier_lag_weeks + d
    if lag < 0:
        raise ValueError(f"supplier lag would be {lag} weeks; it cannot be negative")
    prior = list(params.prior_purchases)
    if lag <= len(prior):
        prior = prior[len(prior) - lag:]  # keep the most recent `lag` values, P_0 last
    elif prior:
        prior = [prior[0]] * (lag - len(prior)) + prior  # extend back with the oldest known value
    else:
        raise ValueError("no pre-horizon purchase is given to extend the payment lag from 0 weeks")
    return _rebuild(params, supplier_lag_weeks=lag, prior_purchases=prior), shock


def _phi_base(params: BusinessParams, shock: ScenarioShock) -> Value | None:
    return None if shock.supplier is None else shock.supplier.dependent_share


def _phi_moved(params: BusinessParams, shock: ScenarioShock, d: int, rel: float) -> Value:
    assert shock.supplier is not None  # guarded by _phi_not_applicable
    return shock.supplier.dependent_share * (1.0 + d * rel)


def _phi_build(params: BusinessParams, shock: ScenarioShock, d: int, rel: float) -> Inputs:
    data = shock.model_dump()
    data["supplier"]["dependent_share"] = _phi_moved(params, shock, d, rel)
    return params, ScenarioShock.model_validate(data)


def _phi_not_applicable(params: BusinessParams, shock: ScenarioShock, plan: ActionPlan) -> str | None:
    if shock.supplier is None:
        return "the scenario has no supplier outage, so the outage share φ does not enter the cash path"
    if shock.supplier.dependent_share == 0.0:
        return "φ is 0, so a relative step does not move it"
    return None


def _optimizer_only(params: BusinessParams, shock: ScenarioShock, plan: ActionPlan) -> str | None:
    return ("used only by the optimizer: simulate() never reads it, so a 0.00 swing would wrongly suggest the credit "
            "line does not matter")


def _no_backup(params: BusinessParams, shock: ScenarioShock, plan: ActionPlan) -> str | None:
    return None if plan.use_backup_supplier else "the plan does not use the backup supplier (x_b = 0)"


def _no_revolver(params: BusinessParams, shock: ScenarioShock, plan: ActionPlan) -> str | None:
    draws = plan.revolver_draw if isinstance(plan.revolver_draw, list) else [plan.revolver_draw]
    if params.revolver_balance_0 == 0.0 and all(d == 0.0 for d in draws):
        return "the revolver is never drawn (B_0 = 0 and no draws in the plan)"
    return None


# Fixed order: also the tie-break order for equal swings.
DRIVERS: tuple[_Driver, ...] = (
    _Driver("store_sales", "Store sales (all stores together)", "S^base", _sales_base, _sales_moved, _sales_build,
            note="Every store's weekly base sales scale by the same factor; S_0 and prior purchases stay fixed."),
    _field_driver("gross_margin", "Gross margin", "g",
                  note="Pre-horizon purchases were bought before week 1 and stay at their recorded value."),
    _field_driver("same_week_collection", "Same-week collection share", "a",
                  note="Moves receipt timing only: receipts over T weeks total S_1+...+S_{T-1} + a S_T + (1-a) S_0."),
    _Driver("supplier_lag_weeks", "Supplier payment lag", "L_p", _lag_base, _lag_moved, _lag_build, integer_step=True,
            note="Whole weeks, so moved by -1 / +1 week, not by the relative step. Prior purchases are trimmed to "
                 "the most recent ones or extended back with the oldest known value."),
    _field_driver("payroll", "Payroll", "W"),
    _field_driver("opex", "Fixed opex", "O"),
    _field_driver("base_rate", "Base rate (all-in, term loan)", "r",
                  note="Relative step on r^base; a scenario rate shock Δr is added on top unchanged."),
    _field_driver("revolver_spread", "Revolver spread", "s_R",
                  note="Revolver interest is B_{t-1}(r_t + s_R)/52, so it acts only when the revolver is drawn.",
                  unused_when=_no_revolver),
    _field_driver("revolver_limit", "Revolver limit", "B-bar",
                  note="An optimizer constraint (§4.2); simulate() does not use it.", unused_when=_optimizer_only),
    _Driver("dependent_share", "Outage-dependent share of sales", "φ", _phi_base, _phi_moved, _phi_build,
            note="Taken from the scenario's supplier outage.", not_applicable=_phi_not_applicable),
    _field_driver("backup_premium", "Backup-supplier premium", "π",
                  note="Acts only when the plan uses the backup supplier (x_b = 1).", unused_when=_no_backup),
    _field_driver("backup_switch_fee", "Backup switching fee", "F_b",
                  note="Acts only when the plan uses the backup supplier (x_b = 1).", unused_when=_no_backup),
)

_ORDER = {d.key: i for i, d in enumerate(DRIVERS)}
_STATUS_ORDER = {"OK": 0, "INFEASIBLE": 1, "NOT_APPLICABLE": 2}


# --------------------------------------------------------------------------- analysis


def _reason(exc: ValueError) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors())
    return str(exc)


def _point(driver: _Driver, params: BusinessParams, shock: ScenarioShock, plan: ActionPlan, d: int, rel: float,
           base_min: float) -> SensitivityPoint:
    value = driver.moved(params, shock, d, rel)
    try:
        p, s = driver.build(params, shock, d, rel)
        res = simulate(p, s, plan)
    except ValueError as exc:  # pydantic's ValidationError is a ValueError too
        return SensitivityPoint(value=value, status="INFEASIBLE", min_cash=None, min_cash_week=None,
                                delta_vs_base=None, reason=_reason(exc))
    return SensitivityPoint(value=value, status="OK", min_cash=res.min_cash, min_cash_week=res.min_cash_week,
                            delta_vs_base=res.min_cash - base_min)


def tornado(params: BusinessParams, shock: ScenarioShock, rel: float = 0.10,
            plan: ActionPlan | None = None) -> TornadoResult:
    """Min cash at each driver moved down / up by ``rel`` (L_p by one week), sorted by swing, largest first.

    ``plan`` defaults to no action. Raises ValueError if ``rel`` is not a positive finite number or if the base
    run itself is rejected by simulate().
    """
    if not (isinstance(rel, int | float) and math.isfinite(rel) and rel > 0):
        raise ValueError(f"rel must be a positive finite number, got {rel!r}")
    plan = ActionPlan() if plan is None else plan
    base = simulate(params, shock, plan)
    pct = f"{rel * 100:g}%"

    entries: list[TornadoEntry] = []
    for drv in DRIVERS:
        step = "-1 / +1 week" if drv.integer_step else f"-{pct} / +{pct}"
        common = dict(key=drv.key, label=drv.label, symbol=drv.symbol, step=step, base_value=drv.base(params, shock))
        why_not = drv.not_applicable(params, shock, plan)
        if why_not is not None:
            entries.append(TornadoEntry(**common, status="NOT_APPLICABLE", low=None, high=None, swing=None,
                                        note=why_not if drv.note is None else f"{why_not}. {drv.note}"))
            continue
        low = _point(drv, params, shock, plan, -1, rel, base.min_cash)
        high = _point(drv, params, shock, plan, +1, rel, base.min_cash)
        ok = low.status == "OK" and high.status == "OK"
        swing = abs(high.min_cash - low.min_cash) if ok else None  # type: ignore[operator]
        max_abs = max(abs(low.delta_vs_base), abs(high.delta_vs_base)) if ok else None  # type: ignore[arg-type]
        entries.append(TornadoEntry(**common, status="OK" if ok else "INFEASIBLE", low=low, high=high, swing=swing,
                                    max_abs_delta=max_abs, note=drv.note))

    entries.sort(key=lambda e: (
        _STATUS_ORDER[e.status],
        -round(e.swing, SWING_TIE_DECIMALS) if e.swing is not None else 0.0,
        _ORDER[e.key],
    ))
    return TornadoResult(scenario_name=shock.name, rel=float(rel), base_min_cash=base.min_cash,
                         base_min_cash_week=base.min_cash_week, entries=entries)
