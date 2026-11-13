"""What the paired bootstrap can detect with few events (MATH_MODEL §6, "What n ≈ 15 can and can't tell us").

Every number here is SYNTHETIC: simulated outcomes and forecasts drawn from seeded generators, never real
cases, market quotes or sealed outcomes. The tests run the repo's own ``paired_bootstrap`` (with a smaller B
than the scorecard's 10,000 where it is only a speed shortcut) and check the approximations written in §6:

  per-event difference   d = Brier(agent) - Brier(market) = (p - q)(p + q - 2y)
  per-event variance     Var(d) = 4 (p - q)^2 pi (1 - pi),  y ~ Bernoulli(pi)
  CI half-width          ~ z_0.975 * sigma_d / sqrt(n)

They also pin down two small-sample effects that §6 warns about: at small n the percentile CI is narrower
than the formula, and a sample in which every outcome is YES can show "agent better" for an agent that is
worse on average.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pytest

from core.evaluator import BOOTSTRAP_SEED, brier, paired_bootstrap

Z = NormalDist().inv_cdf(0.975)  # 1.95996...
PI = 0.85  # ASSUMED probability of YES, roughly a T-7 Fed "hold" price; SYNTHETIC model, not a real quote
FAST_B = 2_000  # speed only; the scorecard always uses B = 10,000


def _briers(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    return (p - y) ** 2


def _sigma_d(delta: float, pi: float) -> float:
    return 2.0 * abs(delta) * math.sqrt(pi * (1.0 - pi))


def _random_sign_model(rng: np.random.Generator, n: int, delta: float = 0.10):
    """SYNTHETIC: calibrated market q = PI, agent p = PI +/- delta (random sign per event), y ~ Bernoulli(PI)."""
    y = (rng.random(n) < PI).astype(float)
    p = PI + delta * rng.choice([-1.0, 1.0], size=n)
    return _briers(p, y), _briers(np.full(n, PI), y)


def _mean_half_width(n: int, reps: int, seed: int) -> float:
    rng = np.random.default_rng(seed)
    hws = []
    for _ in range(reps):
        a, b = _random_sign_model(rng, n)
        r = paired_bootstrap(a, b, n_resamples=FAST_B, seed=int(rng.integers(2**31)))
        hws.append((r.ci_high - r.ci_low) / 2.0)
    return float(np.mean(hws))


# ---------------------------------------------------------------- exact algebra (no randomness)


@pytest.mark.parametrize("p", [0.05, 0.5, 0.75, 0.95])
@pytest.mark.parametrize("q", [0.1, 0.6, 0.85])
@pytest.mark.parametrize("y", [0, 1])
def test_brier_difference_factorises(p, q, y):
    assert brier(p, y) - brier(q, y) == pytest.approx((p - q) * (p + q - 2 * y), abs=1e-15)


@pytest.mark.parametrize("p,q,pi", [(0.95, 0.85, 0.85), (0.75, 0.85, 0.85), (0.85, 0.75, 0.85), (0.6, 0.4, 0.5)])
def test_per_event_mean_and_variance_of_the_difference(p, q, pi):
    """Two-point distribution of d for one event: E[d] = (p-q)(p+q-2pi), Var[d] = 4(p-q)^2 pi(1-pi)."""
    d1, d0 = brier(p, 1) - brier(q, 1), brier(p, 0) - brier(q, 0)
    mean = pi * d1 + (1 - pi) * d0
    var = pi * (d1 - mean) ** 2 + (1 - pi) * (d0 - mean) ** 2
    assert mean == pytest.approx((p - q) * (p + q - 2 * pi), abs=1e-12)
    assert var == pytest.approx(4 * (p - q) ** 2 * pi * (1 - pi), abs=1e-12)


def test_worked_numbers_in_math_model_section_6():
    assert _sigma_d(0.05, PI) == pytest.approx(0.0357, abs=5e-5)
    assert _sigma_d(0.10, PI) == pytest.approx(0.0714, abs=5e-5)
    assert _sigma_d(0.15, PI) == pytest.approx(0.1071, abs=5e-5)
    z80 = NormalDist().inv_cdf(0.80)
    assert Z + z80 == pytest.approx(2.80, abs=0.005)
    s = _sigma_d(0.10, PI)
    # MDE at 50% power (= expected CI half-width) and at 80% power, sigma_d = 0.0714
    assert [round(Z * s / math.sqrt(n), 3) for n in (4, 7, 15, 30)] == [0.070, 0.053, 0.036, 0.026]
    assert [round((Z + z80) * s / math.sqrt(n), 3) for n in (4, 7, 15, 30)] == [0.100, 0.076, 0.052, 0.037]
    # An agent that is exactly right where the market is off by 0.10 gains only delta^2 = 0.01 Brier per event;
    # 80% power for that needs n = ((z + z80) sigma_d / delta^2)^2, about 400 events.
    assert ((Z + z80) * s / 0.10**2) ** 2 == pytest.approx(400, rel=0.01)


# ---------------------------------------------------------------- simulation (SYNTHETIC, seeded)


def test_simulated_ci_half_width_matches_the_formula_and_shrinks_like_one_over_sqrt_n():
    sigma = _sigma_d(0.10, PI)
    hw = {n: _mean_half_width(n, reps=300, seed=8000 + n) for n in (4, 7, 15, 30)}
    formula = {n: Z * sigma / math.sqrt(n) for n in hw}
    ratio = {n: hw[n] / formula[n] for n in hw}

    # n = 15 and 30: the formula (MDE at 50% power) matches the simulated half-width within about 10%.
    assert 0.85 < ratio[15] < 1.05
    assert 0.90 < ratio[30] < 1.05
    # The width shrinks roughly like 1/sqrt(n) ...
    for small, large in ((4, 15), (7, 15), (15, 30)):
        assert hw[small] > hw[large]
        assert hw[small] / hw[large] == pytest.approx(math.sqrt(large / small), rel=0.30)
    # ... but at very small n the percentile CI is narrower than the formula (it under-covers): many SYNTHETIC
    # samples of 4 events contain no NO outcome and give a near-zero width.
    assert ratio[4] < ratio[7] < ratio[15] < 1.0
    assert ratio[4] < 0.8


@pytest.mark.parametrize("n,low,high", [(5, 0.35, 0.55), (15, 0.05, 0.13)])
def test_all_yes_samples_can_make_a_worse_agent_look_better(n, low, high):
    """SYNTHETIC: calibrated market q = 0.85, agent always p = 0.95, y ~ Bernoulli(0.85).

    The agent is worse on average (E[d] = +0.01), so the nominal false "agent better" rate is 2.5%. But in a
    sample with no NO outcome every d_i = -0.02 and the whole bootstrap distribution sits below 0. The rate is
    about 0.85^n: 44% at n = 5, 8.7% at n = 15.
    """
    rng = np.random.default_rng(1500 + n)
    reps, hits = 400, 0
    for _ in range(reps):
        y = (rng.random(n) < PI).astype(float)
        r = paired_bootstrap(
            _briers(np.full(n, 0.95), y), _briers(np.full(n, PI), y), n_resamples=1_000, seed=int(rng.integers(2**31))
        )
        if r.ci_high < 0:
            hits += 1
            assert y.all(), "in this model only an all-YES sample can put the upper bound below 0"
    assert low < hits / reps < high
    assert hits / reps > 0.025


def test_an_exactly_zero_upper_bound_is_left_to_floating_point_rounding():
    """SYNTHETIC: 15 events, one NO; agent 0.85 vs market 0.75 on every event; scorecard defaults (B, seed).

    d_i = -0.04 on the 14 YES events and +0.16 on the NO event. A resample with three copies of the NO event has
    mean exactly 0 in exact arithmetic, and that resample sits at the 97.5th percentile, so the exact upper
    bound is 0 and "CI upper bound < 0" should not hold. In floating point the bound comes out within 1e-15 of
    0 with either sign, so the strict "< 0" verdict is decided by rounding (see MATH_MODEL §6, finding 2).
    """
    y = [0] + [1] * 14
    r = paired_bootstrap([brier(0.85, v) for v in y], [brier(0.75, v) for v in y])
    assert (r.n_resamples, r.seed) == (10_000, BOOTSTRAP_SEED)
    assert r.mean_delta == pytest.approx(-0.4 / 15, abs=1e-12)
    assert abs(r.ci_high) < 1e-15
