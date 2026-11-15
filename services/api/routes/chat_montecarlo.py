"""Monte Carlo tools for the LIVE EXPLORE chat (#209): request validation, the engine adapter, the tool schemas.

The engine (``core/montecarlo.py`` behind ``routes/montecarlo.py``, PR #208) is called only through ``run_decision``
/ ``run_cash`` below, so a change in its Python names is a fix in this adapter alone. Requests are validated here
against the published contract (strict Pydantic, no extra fields) before the engine runs; the engine's answer is
checked for the keys the chat and UI rely on. Any failure comes back to the model as a tool error, never as a
made-up number.

Every result is SIMULATED: the inputs of a decision model are the MODEL's assumptions (ranges it chose, anchored on
cited sources when it has them), so the probabilities are conditional on those assumptions.
"""

from __future__ import annotations

import asyncio
import importlib
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_DECISION_PATHS = 20_000
DEFAULT_CASH_PATHS = 10_000
DEFAULT_SEED = 20261115
MIN_PATHS = 1_000
MAX_DECISION_PATHS = 50_000
MAX_CASH_PATHS = 20_000
CI_LEVEL = 0.95  # the engine's ci95 fields; stated so "95% CI" in a reply matches a tool figure
TOP_SENSITIVITY = 3


class EngineUnavailable(Exception):
    """The Monte Carlo engine (routes/montecarlo.py, PR #208) is not on this server."""


class EngineContractError(Exception):
    """The engine answered with a shape the chat cannot use."""


# --------------------------------------------------------------------------- the adapter (one place to re-point)


def _engine_routes() -> Any:
    """The engine's HTTP route module (PR #208, routes/montecarlo.py), imported on first use: until that PR is on
    this server the tools answer "NOT AVAILABLE". Each call runs the same route function POST /api/montecarlo/*
    runs, in-process (never HTTP to itself), so tool_calls[].input re-POSTs to that route and reproduces it."""
    try:
        return importlib.import_module("routes.montecarlo")
    except ImportError:
        raise EngineUnavailable from None


def _as_dict(out: Any) -> dict[str, Any]:
    if hasattr(out, "model_dump"):
        out = out.model_dump(mode="json")
    if not isinstance(out, dict):
        raise EngineContractError("the Monte Carlo engine returned a non-object")
    return out


def _require_keys(out: dict[str, Any], keys: tuple[str, ...]) -> None:
    missing = [k for k in keys if k not in out]
    if missing:
        raise EngineContractError(f"the Monte Carlo engine response lacks {missing}")
    if out.get("provenance") != "SIMULATED":
        raise EngineContractError("the Monte Carlo engine response is not labelled SIMULATED")


DECISION_KEYS = ("provenance", "n_paths", "seed", "input_sha256", "options", "pairwise", "best", "sensitivity")
CASH_KEYS = ("provenance", "floor", "no_plan", "with_plan")


async def run_decision(body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/montecarlo/decision in-process. Raises EngineUnavailable, RouteError (bad input) or
    EngineContractError."""
    routes_mc = _engine_routes()
    request = routes_mc.DecisionRequest.model_validate(body)
    out = _as_dict(await asyncio.to_thread(routes_mc.decision_montecarlo, request))
    _require_keys(out, DECISION_KEYS)
    return out


async def run_cash(body: dict[str, Any], settings: Any) -> dict[str, Any]:
    """POST /api/montecarlo/cash in-process (it shares /api/optimize's solver slots when with_plan is true)."""
    routes_mc = _engine_routes()
    request = routes_mc.CashRequest.model_validate(body)
    out = _as_dict(await routes_mc.cash_montecarlo(request, settings))
    _require_keys(out, CASH_KEYS)
    return out


# --------------------------------------------------------------------------- request models (the contract)

_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
PARAM_KEYS: dict[str, tuple[str, ...]] = {
    "triangular": ("low", "mode", "high"),
    "normal": ("mean", "sd"),
    "lognormal": ("median", "p90"),
    "uniform": ("low", "high"),
}
_ALL_PARAMS = ("low", "mode", "high", "mean", "sd", "median", "p90")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Source(_Strict):
    url: str = Field(min_length=8, max_length=500, pattern=r"^https?://")
    title: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=300)


class Driver(_Strict):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["value", "event"]
    distribution: Literal["triangular", "normal", "lognormal", "uniform"]
    params: dict[str, float]
    probability: float | None = None
    source: Source | None = None

    @field_validator("params", mode="before")
    @classmethod
    def _drop_null_params(cls, v: Any) -> Any:
        return {k: x for k, x in v.items() if x is not None} if isinstance(v, dict) else v

    @model_validator(mode="after")
    def _check(self) -> Driver:
        need = PARAM_KEYS[self.distribution]
        if set(self.params) != set(need):
            raise ValueError(f"{self.distribution} needs exactly params {list(need)} (others null); got "
                             f"{sorted(self.params)}")
        p = self.params
        if self.distribution == "triangular" and not (p["low"] <= p["mode"] <= p["high"] and p["low"] < p["high"]):
            raise ValueError("triangular needs low <= mode <= high and low < high")
        if self.distribution == "uniform" and not p["low"] < p["high"]:
            raise ValueError("uniform needs low < high")
        if self.distribution == "normal" and not p["sd"] > 0:
            raise ValueError("normal needs sd > 0")
        if self.distribution == "lognormal" and not (p["median"] > 0 and p["p90"] > p["median"]):
            raise ValueError("lognormal needs median > 0 and p90 > median (it models positive amounts)")
        if self.kind == "event":
            if self.probability is None or not 0 < self.probability <= 1:
                raise ValueError("an event driver needs probability in (0, 1]")
        elif self.probability is not None:
            raise ValueError("a value driver takes probability null")
        return self


class Option(_Strict):
    id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=120)
    drivers: list[Driver] = Field(min_length=1, max_length=8)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _ID.match(v):
            raise ValueError("id: lower-case letters, digits, - or _ (e.g. keep, replace)")
        return v


class Metric(_Strict):
    name: str = Field(min_length=1, max_length=120)
    unit: str = Field(min_length=1, max_length=20)
    higher_is_better: bool


class DecisionRequest(_Strict):
    question: str = Field(min_length=1, max_length=300)
    metric: Metric
    options: list[Option] = Field(min_length=2, max_length=4)
    n_paths: int = Field(default=DEFAULT_DECISION_PATHS, ge=MIN_PATHS, le=MAX_DECISION_PATHS)
    seed: int = Field(default=DEFAULT_SEED, ge=0, le=2**32 - 1)

    @field_validator("n_paths", "seed", mode="before")
    @classmethod
    def _null_default(cls, v: Any, info: Any) -> Any:
        if v is None:
            return DEFAULT_DECISION_PATHS if info.field_name == "n_paths" else DEFAULT_SEED
        return v

    @model_validator(mode="after")
    def _unique_ids(self) -> DecisionRequest:
        ids = [o.id for o in self.options]
        if len(set(ids)) != len(ids):
            raise ValueError("option ids must be unique")
        return self


class CashRequest(_Strict):
    scenario_id: str | None = None
    shock: dict[str, Any] | None = None
    protect_payroll: bool = True
    with_plan: bool = True
    n_paths: int = Field(default=DEFAULT_CASH_PATHS, ge=MIN_PATHS, le=MAX_CASH_PATHS)
    seed: int = Field(default=DEFAULT_SEED, ge=0, le=2**32 - 1)

    @field_validator("n_paths", "seed", mode="before")
    @classmethod
    def _null_default(cls, v: Any, info: Any) -> Any:
        if v is None:
            return DEFAULT_CASH_PATHS if info.field_name == "n_paths" else DEFAULT_SEED
        return v


def decision_body(request: DecisionRequest) -> dict[str, Any]:
    """The contract JSON: params only for the chosen distribution, probability only for events."""
    body = request.model_dump(mode="json")
    for option in body["options"]:
        for d in option["drivers"]:
            d["params"] = {k: d["params"][k] for k in PARAM_KEYS[d["distribution"]]}
            if d["kind"] == "value":
                d.pop("probability", None)
    return body


# --------------------------------------------------------------------------- tool schemas (strict-ready)

_NUM_OR_NULL = {"type": ["number", "null"]}


def _obj(properties: dict[str, Any], description: str | None = None, nullable: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"type": ["object", "null"] if nullable else "object", "properties": properties,
                           "required": list(properties), "additionalProperties": False}
    if description:
        out["description"] = description
    return out


DRIVER_SCHEMA = _obj({
    "name": {"type": "string", "description": "What this driver is, e.g. 'execution risk of a CEO transition'."},
    "kind": {"type": "string", "enum": ["value", "event"],
             "description": "value = always happens; event = happens with `probability`, else contributes 0."},
    "distribution": {"type": "string", "enum": ["triangular", "normal", "lognormal", "uniform"]},
    "params": _obj({k: _NUM_OR_NULL for k in _ALL_PARAMS},
                   "Fill only the chosen distribution's keys, the rest null: triangular low, mode, high; normal "
                   "mean, sd; lognormal median, p90 (positive amounts only: never for a downside); uniform low, "
                   "high. In the metric's unit; negative = harm when higher_is_better. For a driver that can be "
                   "negative (a downside or a loss), use triangular or normal."),
    "probability": {**_NUM_OR_NULL, "description": "event only: chance it happens, 0..1; value drivers: null."},
    "source": _obj({"url": {"type": "string"}, "title": {"type": "string"}, "note": {"type": ["string", "null"]}},
                   "The web_search result this range is anchored on (url and title exactly as returned); null when "
                   "the range is your own estimate.", nullable=True),
})

MONTE_CARLO_DECISION_TOOL: dict[str, Any] = {
    "name": "monte_carlo_decision",
    "description": (
        "Monte Carlo comparison of 2-4 options of a real-world decision (SIMULATED). Each option's outcome in ONE "
        "metric (e.g. '5-year shareholder value change, $B') is the sum of 1-8 uncertain drivers you specify. "
        "Returns per option mean / P5 / P50 / P95 and the chance of a loss, the probability each option is best "
        "with a 95% CI, pairwise win probabilities and a driver sensitivity table. Your ranges are assumptions: "
        "anchor them on web_search results (put the url in source) or mark them as your estimate (source null)."),
    "parameters": _obj({
        "question": {"type": "string", "description": "The decision, one line."},
        "metric": _obj({"name": {"type": "string"}, "unit": {"type": "string", "description": "e.g. $B, %, pts"},
                        "higher_is_better": {"type": "boolean"}}),
        "options": {"type": "array", "description": "2 to 4 options, each with a short id (e.g. keep, replace).",
                    "items": _obj({"id": {"type": "string"}, "label": {"type": "string"},
                                   "drivers": {"type": "array", "items": DRIVER_SCHEMA,
                                               "description": "1 to 8 drivers."}})},
        "n_paths": {"type": ["integer", "null"],
                    "description": f"Simulated paths, {MIN_PATHS}..{MAX_DECISION_PATHS}; null = "
                                   f"{DEFAULT_DECISION_PATHS}."},
        "seed": {"type": ["integer", "null"], "description": f"null = {DEFAULT_SEED} (reproducible)."},
    }),
}


def cash_tool(scenario_schema: dict[str, Any], shock_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": "monte_carlo_cash",
        "description": (
            "Monte Carlo version of the SYNTHETIC demo business's 26-week cash simulation (SIMULATED): the shock's "
            "size and timing are drawn around the named scenario or custom shock. Returns the probability that "
            "cash breaches the minimum-cash floor (with a 95% CI) and goes negative, with and without the "
            "payroll-protected recovery plan, plus P5..P95 cash bands per week. The plan is solved once on the "
            "central path and held fixed on every path; plan_central_headroom_over_floor is its headroom there. "
            "Use for 'how likely' / 'what are the odds' questions about the demo business."),
        "parameters": _obj({
            "scenario_id": scenario_schema,
            "shock": shock_schema,
            "protect_payroll": {"type": "boolean", "description": "Always true (payroll protection is a hard rule)."},
            "with_plan": {"type": "boolean", "description": "Also run the recovery plan on every path."},
            "n_paths": {"type": ["integer", "null"],
                        "description": f"{MIN_PATHS}..{MAX_CASH_PATHS}; null = {DEFAULT_CASH_PATHS}."},
            "seed": {"type": ["integer", "null"], "description": f"null = {DEFAULT_SEED}."},
        }),
    }


# --------------------------------------------------------------------------- summaries (what the model sees)


def _get(d: Any, key: str) -> Any:
    return d.get(key) if isinstance(d, dict) else None


def decision_summary(out: dict[str, Any]) -> dict[str, Any]:
    """Compact view for the model: best option with prob_best + CI, P5/P50/P95 per option, the top sensitivity
    rows, the run identity. The full engine response travels separately under `monte_carlo` (UI only)."""
    sens = sorted((s for s in out.get("sensitivity") or [] if isinstance(s, dict)),
                  key=lambda s: -abs(float(s.get("swing") or 0)))[:TOP_SENSITIVITY]
    return {
        "provenance": "SIMULATED",
        "label": out.get("label"),
        "n_paths": out.get("n_paths"),
        "seed": out.get("seed"),
        "input_sha256": out.get("input_sha256"),
        "ci_level": CI_LEVEL,
        "best": out.get("best"),
        "options": [{k: _get(o, k) for k in ("id", "label", "mean", "p5", "p50", "p95", "prob_below_zero")}
                    for o in out.get("options") or []],
        "pairwise": out.get("pairwise"),
        "top_sensitivity": sens,
        "assumptions": out.get("assumptions"),
        "note": "Probabilities are conditional on the model-chosen driver ranges (the tool input), not a forecast.",
    }


def _cash_side(side: Any) -> dict[str, Any] | None:
    if not isinstance(side, dict):
        return None
    return {k: side.get(k) for k in ("prob_below_floor_any", "prob_below_floor_ci95", "prob_negative_any",
                                     "min_cash")}


def cash_summary(out: dict[str, Any]) -> dict[str, Any]:
    return {
        "provenance": "SIMULATED",
        "business_provenance": "SYNTHETIC",
        "n_paths": out.get("n_paths"),
        "seed": out.get("seed"),
        "ci_level": CI_LEVEL,
        "floor": out.get("floor"),
        "no_plan": _cash_side(out.get("no_plan")),
        "with_plan": _cash_side(out.get("with_plan")),
        "plan": out.get("plan"),
        # Computed here, not by the model: the plan is solved on the central path only, so a plan that leaves no
        # headroom over the floor there is fragile once the shock's size and timing vary (#209).
        "plan_central_headroom_over_floor": _headroom(out.get("plan"), out.get("floor")),
        "notes": out.get("notes"),
        "assumptions": out.get("assumptions"),
    }


def _headroom(plan: Any, floor: Any) -> float | None:
    central = _get(plan, "central_min_cash")
    if not isinstance(central, int | float) or not isinstance(floor, int | float):
        return None
    return round(float(central) - float(floor), 2)


__all__ = ["CashRequest", "DecisionRequest", "EngineContractError", "EngineUnavailable", "MONTE_CARLO_DECISION_TOOL",
           "cash_summary", "cash_tool", "decision_body", "decision_summary", "run_cash", "run_decision"]
