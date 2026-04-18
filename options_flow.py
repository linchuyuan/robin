"""
Options flow / unusual activity detector. Computes volume/OI anomalies, pinning
candidates, skew state, and classifies signals per options-flow-detector skill.
Uses the existing get_option_chain / get_yf_option_chain outputs.
"""
from __future__ import annotations

from typing import Any
import math
import statistics


def _strike_list(items: list[dict]) -> list[tuple[float, dict]]:
    return sorted(
        [(float(o.get("strike") or 0), o) for o in (items or []) if o.get("strike") is not None],
        key=lambda x: x[0],
    )


def _delta_25_strikes(chain_side: list[dict], side: str) -> dict | None:
    """Find the strike closest to |delta| = 0.25."""
    candidates = []
    for o in chain_side:
        d = o.get("delta")
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
    """Fit quadratic smile iv(m) = a + b*m + c*m^2. Returns coefficients + R^2."""
    try:
        points = []
        for o in chain_side:
            k = float(o.get("strike") or 0)
            iv = float(o.get("implied_volatility") or 0)
            oi = int(o.get("open_interest") or 0)
            bid = float(o.get("bid") or 0)
            if k <= 0 or iv <= 0 or spot <= 0 or oi < 50 or bid <= 0:
                continue
            points.append((math.log(k / spot), iv))
        if len(points) < 5:
            return {"available": False}

        n = len(points)
        # Build normal equations for least squares on [1, m, m^2]
        Sx = sum(m for m, _ in points)
        Sx2 = sum(m * m for m, _ in points)
        Sx3 = sum(m ** 3 for m, _ in points)
        Sx4 = sum(m ** 4 for m, _ in points)
        Sy = sum(iv for _, iv in points)
        Sxy = sum(m * iv for m, iv in points)
        Sx2y = sum(m * m * iv for m, iv in points)

        # Solve 3x3 system:
        # [n   Sx  Sx2 ] [a]   [Sy  ]
        # [Sx  Sx2 Sx3 ] [b] = [Sxy ]
        # [Sx2 Sx3 Sx4 ] [c]   [Sx2y]
        M = [[n, Sx, Sx2], [Sx, Sx2, Sx3], [Sx2, Sx3, Sx4]]
        Y = [Sy, Sxy, Sx2y]

        def det3(m):
            return (
                m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
            )

        D = det3(M)
        if abs(D) < 1e-12:
            return {"available": False, "reason": "singular_matrix"}

        def replace_col(m, col, v):
            out = [row[:] for row in m]
            for i in range(3):
                out[i][col] = v[i]
            return out

        a = det3(replace_col(M, 0, Y)) / D
        b = det3(replace_col(M, 1, Y)) / D
        c = det3(replace_col(M, 2, Y)) / D

        # R^2
        mean_y = Sy / n
        ss_tot = sum((iv - mean_y) ** 2 for _, iv in points)
        ss_res = sum((iv - (a + b * m + c * m ** 2)) ** 2 for m, iv in points)
        r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        return {
            "available": True,
            "atm_iv": round(a, 4),
            "skew_slope": round(b, 4),
            "smile_curvature": round(c, 4),
            "r_squared": round(r2, 3),
            "points_used": n,
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
    d25_call = _delta_25_strikes(calls, "call")
    d25_put = _delta_25_strikes(puts, "put")
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
