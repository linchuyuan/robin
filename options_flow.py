"""
Options flow / unusual activity detector. Computes volume/OI anomalies, pinning
candidates, skew state, and classifies signals per options-flow-detector skill.
Uses the existing get_option_chain / get_yf_option_chain outputs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import math
import statistics

try:
    from quant import calculate_greeks
except ImportError:
    calculate_greeks = None


def _compute_delta_if_missing(opt: dict, spot: float, expiration_date: str | None, side: str) -> float | None:
    """
    Fallback Black-Scholes delta when Yahoo chain lacks the field. Robinhood
    chain provides delta natively; this is only exercised on Yahoo path.
    """
    d = opt.get("delta")
    if d is not None:
        try:
            return float(d)
        except (TypeError, ValueError):
            pass
    if calculate_greeks is None or not expiration_date:
        return None
    try:
        strike = float(opt.get("strike") or 0)
        iv = float(opt.get("implied_volatility") or 0)
        if strike <= 0 or iv <= 0 or spot <= 0:
            return None
        exp_dt = datetime.strptime(expiration_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        ttm_years = max(0.001, (exp_dt - datetime.now(timezone.utc)).total_seconds() / 31557600.0)
        g = calculate_greeks(S=spot, K=strike, T=ttm_years, r=0.045, sigma=iv, q=0.0, option_type=side)
        return g.get("delta")
    except Exception:
        return None


def _strike_list(items: list[dict]) -> list[tuple[float, dict]]:
    return sorted(
        [(float(o.get("strike") or 0), o) for o in (items or []) if o.get("strike") is not None],
        key=lambda x: x[0],
    )


def _delta_25_strikes(chain_side: list[dict], side: str, spot: float = 0.0, expiration_date: str | None = None) -> dict | None:
    """Find the strike closest to |delta| = 0.25. Falls back to BS-computed delta
    when chain lacks the field (Yahoo path)."""
    candidates = []
    for o in chain_side:
        d = _compute_delta_if_missing(o, spot, expiration_date, side)
        if d is None:
            continue
        try:
            d_val = abs(float(d))
            candidates.append((abs(d_val - 0.25), o))
        except Exception:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def fit_vol_smile(chain_side: list[dict], spot: float) -> dict:
    """Fit quadratic smile iv(m) = a + b*m + c*m^2. Uses numpy lstsq."""
    try:
        import numpy as np
    except ImportError:
        return {"available": False, "reason": "numpy_unavailable"}
    try:
        xs: list[float] = []
        ys: list[float] = []
        for o in chain_side:
            k = float(o.get("strike") or 0)
            iv = float(o.get("implied_volatility") or 0)
            oi = int(o.get("open_interest") or 0)
            bid = float(o.get("bid") or 0)
            if k <= 0 or iv <= 0 or spot <= 0 or oi < 50 or bid <= 0:
                continue
            xs.append(math.log(k / spot))
            ys.append(iv)
        n = len(xs)
        if n < 5:
            return {"available": False, "reason": "too_few_liquid_strikes"}

        m = np.asarray(xs, dtype=float)
        y = np.asarray(ys, dtype=float)
        X = np.column_stack([np.ones(n), m, m * m])

        betas, *_ = np.linalg.lstsq(X, y, rcond=None)
        a, b, c = float(betas[0]), float(betas[1]), float(betas[2])

        y_hat = X @ betas
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        # Condition number check — warn on near-singular design
        cond = float(np.linalg.cond(X))
        stability = "stable" if cond < 1e4 else "unstable"

        return {
            "available": True,
            "atm_iv": round(a, 4),
            "skew_slope": round(b, 4),
            "smile_curvature": round(c, 4),
            "r_squared": round(r2, 3),
            "points_used": n,
            "condition_number": round(cond, 1),
            "stability": stability,
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


def detect_unusual_activity(chain: dict) -> dict:
    """
    Given a get_option_chain / get_yf_option_chain response dict, compute
    unusual-activity metrics and classify signals.
    """
    calls = chain.get("calls") or []
    puts = chain.get("puts") or []
    spot = float(chain.get("current_price") or 0)
    if spot <= 0:
        return {"available": False, "reason": "no_spot_price"}

    symbol = chain.get("symbol")
    expiration = chain.get("expiration_date")

    # Chain totals and PCRs
    total_call_vol = sum(int(c.get("volume") or 0) for c in calls)
    total_put_vol = sum(int(p.get("volume") or 0) for p in puts)
    total_call_oi = sum(int(c.get("open_interest") or 0) for c in calls)
    total_put_oi = sum(int(p.get("open_interest") or 0) for p in puts)

    volume_pcr = total_put_vol / total_call_vol if total_call_vol > 0 else None
    oi_pcr = total_put_oi / total_call_oi if total_call_oi > 0 else None

    # V/OI anomalies
    unusual_strikes = []
    for side_name, side in (("call", calls), ("put", puts)):
        for opt in side:
            vol = int(opt.get("volume") or 0)
            oi = int(opt.get("open_interest") or 0)
            if vol < 500 or oi == 0:
                continue
            v_over_oi = vol / max(1, oi)
            if v_over_oi > 3:
                strike = float(opt.get("strike") or 0)
                distance_pct = (strike - spot) / spot if spot > 0 else 0
                unusual_strikes.append({
                    "strike": strike,
                    "side": side_name,
                    "volume": vol,
                    "open_interest": oi,
                    "vol_over_oi": round(v_over_oi, 2),
                    "distance_pct": round(distance_pct, 4),
                })
    unusual_strikes.sort(key=lambda x: x["vol_over_oi"], reverse=True)

    # OI clusters within ±5% of spot
    band_lower = spot * 0.95
    band_upper = spot * 1.05
    band_strikes: dict[float, dict] = {}
    for side_name, side in (("call", calls), ("put", puts)):
        for opt in side:
            strike = float(opt.get("strike") or 0)
            if not (band_lower <= strike <= band_upper):
                continue
            row = band_strikes.setdefault(strike, {"strike": strike, "call_oi": 0, "put_oi": 0})
            if side_name == "call":
                row["call_oi"] += int(opt.get("open_interest") or 0)
            else:
                row["put_oi"] += int(opt.get("open_interest") or 0)

    band_rows = list(band_strikes.values())
    for r in band_rows:
        r["total_oi"] = r["call_oi"] + r["put_oi"]
        r["distance_pct"] = round((r["strike"] - spot) / spot, 4) if spot else 0
    band_rows.sort(key=lambda r: r["total_oi"], reverse=True)

    median_band_oi = (
        statistics.median([r["total_oi"] for r in band_rows])
        if band_rows else 0
    )
    top_cluster = band_rows[0] if band_rows else None
    pin_risk = None
    if top_cluster and median_band_oi > 0 and top_cluster["total_oi"] > 3 * median_band_oi:
        pin_risk = {
            "level": "high",
            "strike": top_cluster["strike"],
            "total_oi": top_cluster["total_oi"],
            "distance_pct": top_cluster["distance_pct"],
        }

    # Smile fit (calls + puts together for robustness)
    combined = calls + puts
    smile = fit_vol_smile(combined, spot)
    atm_iv = smile.get("atm_iv") if smile.get("available") else None
    skew_slope = smile.get("skew_slope") if smile.get("available") else None

    # RR25 (25-delta call IV minus 25-delta put IV)
    d25_call = _delta_25_strikes(calls, "call", spot=spot, expiration_date=expiration)
    d25_put = _delta_25_strikes(puts, "put", spot=spot, expiration_date=expiration)
    rr25 = None
    if d25_call and d25_put:
        c_iv = float(d25_call.get("implied_volatility") or 0)
        p_iv = float(d25_put.get("implied_volatility") or 0)
        if c_iv > 0 and p_iv > 0:
            rr25 = round((c_iv - p_iv) * 100, 2)  # in vol-points

    # Signal classification
    signals = []
    if unusual_strikes:
        bullish_blocks = [s for s in unusual_strikes if s["side"] == "call" and s["distance_pct"] >= 0 and s["distance_pct"] <= 0.03]
        bearish_blocks = [s for s in unusual_strikes if s["side"] == "put" and s["distance_pct"] <= 0 and s["distance_pct"] >= -0.03]
        if len(bullish_blocks) >= 2:
            signals.append({"type": "bullish_block", "strength": "strong", "strikes": bullish_blocks[:5]})
        if len(bearish_blocks) >= 2:
            signals.append({"type": "bearish_block", "strength": "strong", "strikes": bearish_blocks[:5]})

    if pin_risk:
        signals.append({"type": "pin_risk", "strength": pin_risk["level"], "strike": pin_risk["strike"]})

    if rr25 is not None:
        if rr25 < -4:
            signals.append({"type": "put_skew_extreme", "rr25": rr25})
        elif rr25 > 4:
            signals.append({"type": "call_skew_extreme", "rr25": rr25})

    if not signals:
        signals.append({"type": "no_signal"})

    return {
        "available": True,
        "symbol": symbol,
        "expiration": expiration,
        "spot": spot,
        "volume_pcr": round(volume_pcr, 3) if volume_pcr is not None else None,
        "oi_pcr": round(oi_pcr, 3) if oi_pcr is not None else None,
        "smile": smile,
        "rr25_vol_points": rr25,
        "unusual_strikes": unusual_strikes[:10],
        "top_oi_clusters": band_rows[:3],
        "pin_risk": pin_risk,
        "signals": signals,
    }
