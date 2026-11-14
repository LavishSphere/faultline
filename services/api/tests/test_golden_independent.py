"""Engine vs an independent hand model of the bad-quarter scenario (issue #108).

The golden file tests/golden/bad_quarter_independent.csv comes from the spreadsheet
docs/finance/bad_quarter_independent.xlsx, built from docs/MATH_MODEL.md §1-§3 and the §10 parameters
without reading or running the engine. Its formulas were evaluated to produce the CSV.

Plan: do nothing (all §4 decisions are 0). Shock: the "bad-quarter" entry of data/scenarios.json
(+2% rate from week 1; -20% demand in weeks 3-8 with a 4-week recovery; primary supplier down in weeks 5-7).

Hand check of the end point: the base business loses 1,423.08 a week; the +2% rate adds
600,000 x 2% / 52 = 230.77 a week, so 26 weeks cost 26 x 1,653.85 = 43,000. Lost sales total 123,000
(weeks 3-11) and cost their 35% gross margin, 43,050, all inside the horizon.
C_26 = 100,000 - 43,000 - 43,050 = 13,950. First week below C_min = 25,000: week 20 (23,873.08).
"""

from __future__ import annotations

import csv
import dataclasses
from pathlib import Path

import pytest

from config import get_settings
from core.financials import ActionPlan, simulate
from routes.scenarios import load_scenarios
from routes.simulate import load_business

DATA = Path(__file__).resolve().parent.parent / "data"
GOLDEN = Path(__file__).resolve().parent / "golden" / "bad_quarter_independent.csv"
SETTINGS = dataclasses.replace(get_settings(), data_dir=DATA)
TOL = 0.01  # dollars
C_MIN = 25_000.0  # §10 liquidity floor


def _golden_rows() -> list[dict[str, float]]:
    # newline="" lets the csv module accept both LF and CRLF (core.autocrlf may convert on checkout).
    with GOLDEN.open(newline="", encoding="utf-8") as fh:
        return [{k: float(v) for k, v in row.items()} for row in csv.DictReader(fh)]


GOLDEN_ROWS = _golden_rows()


@pytest.fixture(scope="module")
def engine():
    business = load_business(SETTINGS)  # the same loader POST /api/simulate uses
    scenarios = {s.id: s for s in load_scenarios(SETTINGS)}  # the same loader GET /api/scenarios uses
    return simulate(business, scenarios["bad-quarter"].shock, ActionPlan())


def test_golden_file_shape():
    assert [int(r["week"]) for r in GOLDEN_ROWS] == list(range(1, 27))
    assert list(GOLDEN_ROWS[0]) == ["week", "sales", "receipts", "purchases", "inventory", "interest", "cash"]


def test_engine_horizon_matches(engine):
    assert engine.weeks == list(range(1, 27))


@pytest.mark.parametrize("row", GOLDEN_ROWS, ids=lambda r: f"week{int(r['week'])}")
def test_cash_matches_independent_model(engine, row):
    t = int(row["week"])
    assert engine.cash[t - 1] == pytest.approx(row["cash"], abs=TOL)


@pytest.mark.parametrize("column, field", [
    ("sales", "sales"),
    ("receipts", "receipts"),
    ("purchases", "purchases"),
    ("inventory", "inventory"),
    ("interest", "total_interest"),
])
def test_intermediate_columns_match(engine, column, field):
    expected = [r[column] for r in GOLDEN_ROWS]
    assert getattr(engine, field) == pytest.approx(expected, abs=TOL)


def test_headline_numbers(engine):
    assert engine.ending_cash == pytest.approx(13_950.0, abs=TOL)
    below = [t for t, c in zip(engine.weeks, engine.cash, strict=True) if c < C_MIN]
    assert below[0] == 20

