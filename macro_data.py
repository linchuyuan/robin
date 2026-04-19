"""
Macro regime data: yield-curve proxy, credit-spread proxy, VIX term structure,
and a composite regime dashboard. Uses yfinance (free) — no FRED API required.

Hardened: in-process TTL cache (30 min) to avoid hammering yfinance on repeated
runs; graceful degradation with explicit error reasons.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import yfinance as yf
import pandas as pd


_DOWNLOAD_CACHE: dict[tuple[str, str], tuple[float, pd.Series]] = {}
_CACHE_TTL_SEC = int(os.getenv("ROBIN_MACRO_CACHE_TTL_SEC", "1800"))  # 30 min


def _safe_pct_change(series: pd.Series, periods: int) -> float | None:
    if series is None or series.empty or len(series) < periods + 1:
        return None
    try:
        latest = float(series.iloc[-1])
        earlier = float(series.iloc[-periods - 1])
        if earlier == 0:
            return None
        return (latest / earlier) - 1.0
    except Exception:
        return None


def _download_close(symbol: str, period: str = "3mo") -> pd.Series:
    """Download daily closes with TTL cache. Retries once on transient failure."""
    key = (symbol, period)
    cached = _DOWNLOAD_CACHE.get(key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL_SEC:
        return cached[1]

    for attempt in range(2):
        try:
            data = yf.download(symbol, period=period, progress=False, auto_adjust=True)
            if data is None or data.empty:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                break
            if isinstance(data.columns, pd.MultiIndex):
                col = data["Close"] if "Close" in data.columns.get_level_values(0) else data
                if isinstance(col, pd.DataFrame):
                    col = col.iloc[:, 0]
                series = col.dropna()
            elif "Close" in data.columns:
                series = data["Close"].dropna()
            else:
                series = data.iloc[:, 0].dropna()
            _DOWNLOAD_CACHE[key] = (time.time(), series)
            return series
        except Exception:
            if attempt == 0:
                time.sleep(0.5)
                continue
            break
    # Final fallback: empty series (but don't overwrite a stale cache entry with empty)
    return pd.Series(dtype=float)


def get_yield_curve_proxy() -> dict:
    """
    Approximate the 10Y-2Y spread using TLT (20+Y Treasury) vs SHY (1-3Y) price behavior.
    Not a direct spread; this is a *regime proxy* — use sign + trend, not level.
    """
    tlt = _download_close("TLT", "3mo")
    shy = _download_close("SHY", "3mo")
    if tlt.empty or shy.empty:
        return {"error": "No data", "available": False}

    tlt_ret_20d = _safe_pct_change(tlt, 20)
    shy_ret_20d = _safe_pct_change(shy, 20)
    # Spread proxy: when TLT underperforms SHY, long rates rising faster than short → flattening/steepening depends on context.
    # A simple flag: if TLT dropped > 3% while SHY flat/up, curve likely flattening/inverting (long rates up).
    signal = "neutral"
    if tlt_ret_20d is not None and shy_ret_20d is not None:
        rel = tlt_ret_20d - shy_ret_20d
        if rel < -0.03:
            signal = "rates_rising_long_end"
        elif rel > 0.03:
            signal = "long_duration_rally_curve_steepening"

    return {
        "available": True,
        "tlt_20d_return": tlt_ret_20d,
        "shy_20d_return": shy_ret_20d,
        "relative_return_20d": (tlt_ret_20d - shy_ret_20d) if tlt_ret_20d is not None and shy_ret_20d is not None else None,
        "signal": signal,
        "note": "proxy only; for exact 10Y-2Y use FRED if available",
    }


def get_credit_spread_proxy() -> dict:
    """
    HYG (High-Yield bond ETF) vs LQD (Investment-Grade bond ETF) returns.
    Negative HYG-LQD spread return = credit widening = risk-off.
    """
    hyg = _download_close("HYG", "3mo")
    lqd = _download_close("LQD", "3mo")
    if hyg.empty or lqd.empty:
        return {"error": "No data", "available": False}

    hyg_ret_20d = _safe_pct_change(hyg, 20)
    lqd_ret_20d = _safe_pct_change(lqd, 20)
    rel = None
    state = "neutral"
    if hyg_ret_20d is not None and lqd_ret_20d is not None:
        rel = hyg_ret_20d - lqd_ret_20d
        if rel < -0.015:
            state = "credit_widening"
        elif rel > 0.01:
            state = "credit_tightening"

    return {
        "available": True,
        "hyg_20d_return": hyg_ret_20d,
        "lqd_20d_return": lqd_ret_20d,
        "hyg_lqd_spread_return_20d": rel,
        "state": state,
    }


def get_vix_term_structure() -> dict:
    """
    Spot VIX vs VIX 3-month (VXV ticker historically; VIX3M via CBOE).
    Backwardation (spot > VXV) is a strong stress signal.
    """
    try:
        vix = _download_close("^VIX", "1mo")
        vxv = _download_close("^VIX3M", "1mo")
        if vix.empty:
            return {"error": "No VIX data", "available": False}
        vix_level = float(vix.iloc[-1])
        vxv_level = float(vxv.iloc[-1]) if not vxv.empty else None

        state = "flat"
        if vxv_level:
            if vix_level > vxv_level + 2:
                state = "backwardation"
            elif vix_level < vxv_level - 2:
                state = "contango"

        return {
            "available": True,
            "vix_spot": round(vix_level, 2),
            "vix_3m": round(vxv_level, 2) if vxv_level else None,
            "spread_points": round(vix_level - vxv_level, 2) if vxv_level else None,
            "state": state,
        }
    except Exception as e:
        return {"error": str(e), "available": False}


def get_flight_to_quality() -> dict:
    """
    GLD vs SPY 5-day relative return. Gold outperforming SPY during VIX spike = flight-to-quality.
    """
    spy = _download_close("SPY", "1mo")
    gld = _download_close("GLD", "1mo")
    if spy.empty or gld.empty:
        return {"available": False}
    spy_5d = _safe_pct_change(spy, 5)
    gld_5d = _safe_pct_change(gld, 5)
    if spy_5d is None or gld_5d is None:
        return {"available": False}
    return {
        "available": True,
        "spy_5d_return": spy_5d,
        "gld_5d_return": gld_5d,
        "gold_outperformance_5d": gld_5d - spy_5d,
        "flight_to_quality_active": (gld_5d - spy_5d) > 0.02 and spy_5d < -0.02,
    }


def get_regime_dashboard() -> dict:
    """
    Composite regime snapshot combining curve / credit / VIX / flight-to-quality.
    Feeds the macro-regime-classifier skill but callable standalone.
    """
    curve = get_yield_curve_proxy()
    credit = get_credit_spread_proxy()
    vix_term = get_vix_term_structure()
    ftq = get_flight_to_quality()

    vix_spot = (vix_term or {}).get("vix_spot")
    credit_state = (credit or {}).get("state", "neutral")
    curve_signal = (curve or {}).get("signal", "neutral")
    term_state = (vix_term or {}).get("state", "flat")
    ftq_active = bool((ftq or {}).get("flight_to_quality_active"))

    # Heuristic regime mapping
    regime = "neutral"
    confidence = 0.5
    if vix_spot and vix_spot > 30 and credit_state == "credit_widening":
        regime = "panic"
        confidence = 0.8
    elif vix_spot and vix_spot > 25 and credit_state == "credit_widening":
        regime = "slowdown"
        confidence = 0.7
    elif term_state == "backwardation" and credit_state == "credit_widening":
        regime = "late_cycle"
        confidence = 0.65
    elif credit_state == "credit_tightening" and (vix_spot or 0) < 18:
        regime = "expansion"
        confidence = 0.7
    elif ftq_active:
        regime = "late_cycle"
        confidence = 0.6

    return {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "regime": regime,
        "confidence": confidence,
        "components": {
            "yield_curve": curve,
            "credit_spread": credit,
            "vix_term_structure": vix_term,
            "flight_to_quality": ftq,
        },
    }


def get_sector_breadth() -> dict:
    """Fraction of 11 sector ETFs positive over 5 and 20 day windows."""
    sectors = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLC", "XLY", "XLP", "XLU", "XLRE", "XLB"]
    pos_5d = 0
    pos_20d = 0
    details = []
    for s in sectors:
        series = _download_close(s, "3mo")
        if series.empty:
            continue
        r5 = _safe_pct_change(series, 5)
        r20 = _safe_pct_change(series, 20)
        if r5 is not None and r5 > 0:
            pos_5d += 1
        if r20 is not None and r20 > 0:
            pos_20d += 1
        details.append({"symbol": s, "return_5d": r5, "return_20d": r20})

    n = len(sectors)
    pct_5d = pos_5d / n if n else 0.0
    state = "healthy" if pct_5d > 0.6 else "weak" if pct_5d < 0.3 else "neutral"
    return {
        "pct_positive_5d": round(pct_5d, 3),
        "pct_positive_20d": round(pos_20d / n, 3),
        "state": state,
        "sectors": details,
    }
