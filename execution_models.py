"""
Execution modeling: empirical slippage curves and VWAP execution helper.

Replaces the prior flat 5bps slippage assumption in backtest_engine.py with a
size/volatility/time-of-day aware model calibrated to published microstructure
research. Calibration constants are defaults; override via env vars for
production once live slippage data is collected (see drift_monitor.py).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SlippageParams:
    # Permanent impact coefficient (linear in sqrt of size/ADV)
    impact_coef: float = 0.30
    # Temporary impact coefficient
    temp_impact_coef: float = 0.10
    # Half-spread base (bps) for liquid large-caps
    half_spread_bps_base: float = 1.5
    # Multiplier for half-spread in mid/small-cap
    mid_cap_mult: float = 2.0
    small_cap_mult: float = 4.0
    # Volatility scaling (per 1 vol-point annualized)
    vol_scale: float = 0.12


_DEFAULT = SlippageParams()


def _liquidity_bucket(adv_usd: float) -> str:
    if adv_usd >= 5e8:
        return "large"
    if adv_usd >= 5e7:
        return "mid"
    return "small"


def _time_of_day_multiplier(minute_of_day: int) -> float:
    """
    Intraday slippage U-shape. Assumes 390-minute regular session (9:30-16:00 ET).
    First 15m and last 15m are roughly 2x baseline; middle is 1x.
    """
    if minute_of_day is None:
        return 1.0
    if minute_of_day < 15:
        return 2.2
    if minute_of_day < 30:
        return 1.4
    if minute_of_day > 375:  # last 15m
        return 2.0
    if minute_of_day > 360:
        return 1.3
    return 1.0


def estimate_slippage_bps(
    *,
    order_notional_usd: float,
    adv_usd: float,
    vol_20d_annual: float,
    minute_of_day: int | None = None,
    params: SlippageParams | None = None,
) -> dict:
    """
    Return expected one-way slippage in basis points for a market-style fill.

    Model: half_spread + impact·sqrt(size_frac_adv) + vol_scale·volatility_points,
    with multipliers for liquidity bucket and time-of-day.

    Args:
        order_notional_usd: Dollar size of the order ($ notional).
        adv_usd: 20-day average daily dollar volume for the symbol.
        vol_20d_annual: Realized annualized volatility (decimal, e.g., 0.25).
        minute_of_day: Minutes since 9:30 ET (0-390). None = midday default.

    Returns:
        dict with keys: slippage_bps, components, bucket, size_frac_adv
    """
    p = params or _DEFAULT
    adv_usd = max(1.0, float(adv_usd))
    size_frac = max(0.0, float(order_notional_usd)) / adv_usd

    bucket = _liquidity_bucket(adv_usd)
    if bucket == "large":
        spread_bps = p.half_spread_bps_base
    elif bucket == "mid":
        spread_bps = p.half_spread_bps_base * p.mid_cap_mult
    else:
        spread_bps = p.half_spread_bps_base * p.small_cap_mult

    impact_bps = p.impact_coef * (size_frac ** 0.5) * 10_000
    temp_impact_bps = p.temp_impact_coef * size_frac * 10_000
    vol_bps = p.vol_scale * max(0.0, float(vol_20d_annual)) * 100

    tod_mult = _time_of_day_multiplier(minute_of_day if minute_of_day is not None else 195)
    total_bps = (spread_bps + impact_bps + temp_impact_bps + vol_bps) * tod_mult

    return {
        "slippage_bps": round(total_bps, 2),
        "components": {
            "half_spread_bps": round(spread_bps * tod_mult, 2),
            "permanent_impact_bps": round(impact_bps * tod_mult, 2),
            "temporary_impact_bps": round(temp_impact_bps * tod_mult, 2),
            "volatility_component_bps": round(vol_bps * tod_mult, 2),
            "time_of_day_multiplier": round(tod_mult, 2),
        },
        "bucket": bucket,
        "size_frac_adv": round(size_frac, 6),
    }


def vwap_slice_plan(
    *,
    total_qty: float,
    volume_profile_pct: Iterable[float],
    slice_min: int = 15,
) -> list[dict]:
    """
    Produce a VWAP-sliced execution plan.

    Args:
        total_qty: Total shares to execute.
        volume_profile_pct: Intraday volume fractions summing to ~1.0, one per bar.
        slice_min: Minutes per slice bar (default 15).

    Returns a list of {minute_of_day, shares, fraction} dicts.
    """
    profile = [max(0.0, float(p)) for p in volume_profile_pct]
    s = sum(profile) or 1.0
    profile = [p / s for p in profile]
    plan = []
    cumulative = 0
    for i, frac in enumerate(profile):
        shares = round(total_qty * frac)
        if i == len(profile) - 1:
            # reconcile rounding
            shares = int(total_qty - cumulative)
        else:
            cumulative += shares
        plan.append({
            "minute_of_day": i * slice_min,
            "shares": shares,
            "fraction": round(frac, 4),
        })
    return plan


def default_us_equity_volume_profile(slice_min: int = 15) -> list[float]:
    """
    Typical U-shape volume profile for U.S. equities across 26 bars of 15 minutes.
    First 15m ~ 13% of day, last 15m ~ 11%, midday bars ~ 2.5-3%.
    """
    # 26 bars of 15min over 390-min session
    if slice_min != 15:
        # Simple scaling: same shape, more/fewer bars
        n = max(1, 390 // slice_min)
        base = default_us_equity_volume_profile(15)
        # interpolate (very rough)
        step = len(base) / n
        out = [base[min(int(i * step), len(base) - 1)] for i in range(n)]
        total = sum(out) or 1.0
        return [v / total for v in out]
    return [
        0.130, 0.070, 0.055, 0.045, 0.040,
        0.035, 0.032, 0.030, 0.028, 0.026,
        0.024, 0.024, 0.024, 0.024, 0.024,
        0.026, 0.028, 0.030, 0.032, 0.035,
        0.040, 0.045, 0.055, 0.070, 0.090,
        0.110,
    ]


def _env_slippage_params() -> SlippageParams:
    """Allow tuning via env vars after live calibration via drift_monitor."""
    try:
        return SlippageParams(
            impact_coef=float(os.getenv("ROBIN_SLIP_IMPACT", _DEFAULT.impact_coef)),
            temp_impact_coef=float(os.getenv("ROBIN_SLIP_TEMP", _DEFAULT.temp_impact_coef)),
            half_spread_bps_base=float(os.getenv("ROBIN_SLIP_HALFSPREAD", _DEFAULT.half_spread_bps_base)),
            mid_cap_mult=float(os.getenv("ROBIN_SLIP_MIDMULT", _DEFAULT.mid_cap_mult)),
            small_cap_mult=float(os.getenv("ROBIN_SLIP_SMALLMULT", _DEFAULT.small_cap_mult)),
            vol_scale=float(os.getenv("ROBIN_SLIP_VOLSCALE", _DEFAULT.vol_scale)),
        )
    except Exception:
        return _DEFAULT
