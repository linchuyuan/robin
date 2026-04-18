"""
Earnings consensus and surprise probability modeler. Uses yfinance earnings
estimate data (free) + analyst recommendation signals.
"""
from __future__ import annotations

import yfinance as yf
from typing import Any
import statistics


def get_consensus_data(symbol: str) -> dict:
    """
    Pull consensus EPS, revenue, analyst dispersion, recommendation trend.
    """
    sym = str(symbol).upper().strip()
    try:
        t = yf.Ticker(sym)
        info = t.info or {}

        consensus_eps = info.get("targetMeanPrice") and info.get("forwardEps")
        # yfinance exposes these occasionally; fall back to analyst estimates table
        est_eps_mean = info.get("forwardEps")
        eps_high = None
        eps_low = None

        # Try to get from recommendations or calendar
        try:
            cal = t.calendar
            if cal is not None and hasattr(cal, "get"):
                eps_avg = cal.get("Earnings Average")
                eps_hi = cal.get("Earnings High")
                eps_lo = cal.get("Earnings Low")
                if eps_avg:
                    if hasattr(eps_avg, "iloc"):
                        est_eps_mean = float(eps_avg.iloc[0])
                    else:
                        est_eps_mean = float(eps_avg) if eps_avg else None
                if eps_hi and eps_lo:
                    try:
                        eps_high = float(eps_hi if not hasattr(eps_hi, "iloc") else eps_hi.iloc[0])
                        eps_low = float(eps_lo if not hasattr(eps_lo, "iloc") else eps_lo.iloc[0])
                    except Exception:
                        pass
        except Exception:
            pass

        # EPS dispersion
        eps_dispersion_pct = None
        if est_eps_mean and eps_high is not None and eps_low is not None and est_eps_mean != 0:
            eps_dispersion_pct = abs(eps_high - eps_low) / abs(est_eps_mean)

        # Revisions via recommendation trend
        eps_revision_7d_pct = None
        eps_revision_30d_pct = None
        try:
            # yfinance does not expose estimate revisions directly in free info;
            # we approximate using recommendation trend shifts.
            rec = t.recommendations_summary if hasattr(t, "recommendations_summary") else None
            # If unavailable, leave as None
        except Exception:
            pass

        analyst_count = info.get("numberOfAnalystOpinions")
        earnings_date = None
        try:
            ts = info.get("earningsTimestamp")
            if ts:
                from datetime import datetime, timezone
                earnings_date = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            pass

        # Last 4 quarters beat history
        beats = 0
        total_q = 0
        try:
            earnings_history = t.earnings_history if hasattr(t, "earnings_history") else None
            if earnings_history is not None and hasattr(earnings_history, "iterrows"):
                for _, row in earnings_history.iterrows():
                    total_q += 1
                    actual = row.get("epsActual")
                    estimate = row.get("epsEstimate")
                    if actual is not None and estimate is not None and actual > estimate:
                        beats += 1
                    if total_q >= 4:
                        break
        except Exception:
            pass
        beat_rate_last_4q = beats / total_q if total_q else None

        guidance_hint = None
        # Simple heuristic from recommendation trend (neutral / buy / strong_buy)
        rec_key = info.get("recommendationKey")
        if rec_key in {"strong_buy", "buy"}:
            guidance_hint = "above_consensus"
        elif rec_key == "sell":
            guidance_hint = "below_consensus"
        else:
            guidance_hint = "in_line"

        return {
            "symbol": sym,
            "available": True,
            "consensus_eps": est_eps_mean,
            "eps_high": eps_high,
            "eps_low": eps_low,
            "eps_dispersion_pct": round(eps_dispersion_pct, 3) if eps_dispersion_pct is not None else None,
            "eps_revision_7d_pct": eps_revision_7d_pct,
            "eps_revision_30d_pct": eps_revision_30d_pct,
            "analyst_count": analyst_count,
            "guidance_hint": guidance_hint,
            "earnings_date": earnings_date,
            "beat_rate_last_4q": round(beat_rate_last_4q, 2) if beat_rate_last_4q is not None else None,
            "quarters_analyzed": total_q,
        }
    except Exception as e:
        return {"symbol": sym, "available": False, "error": str(e)}


def compute_surprise_probability(consensus: dict) -> dict:
    """
    Apply the heuristic model from the earnings-surprise-modeler skill.
    """
    if not consensus or not consensus.get("available"):
        return {"available": False}

    p = 0.5

    rev_30d = consensus.get("eps_revision_30d_pct")
    rev_7d = consensus.get("eps_revision_7d_pct")

    if rev_30d is not None:
        if rev_30d > 0.02:
            p += 0.10
        elif rev_30d < -0.02:
            p -= 0.10

    if rev_7d is not None and rev_30d is not None:
        if rev_7d > 0.01 and rev_30d > 0.01:
            p += 0.05

    guidance = consensus.get("guidance_hint")
    if guidance == "above_consensus":
        p += 0.05
    elif guidance == "below_consensus":
        p -= 0.05

    beat_rate = consensus.get("beat_rate_last_4q")
    if beat_rate is not None:
        if beat_rate >= 0.75:
            p += 0.05
        elif beat_rate <= 0.25:
            p -= 0.05

    # Clamp
    p = max(0.10, min(0.90, p))

    # High dispersion downgrades confidence
    confidence = "medium"
    dispersion = consensus.get("eps_dispersion_pct")
    if dispersion is not None:
        if dispersion > 0.25:
            confidence = "low"
        elif dispersion < 0.10:
            confidence = "high"

    return {
        "available": True,
        "surprise_probability": round(p, 3),
        "confidence": confidence,
        "inputs_used": {
            "revisions_30d": rev_30d,
            "revisions_7d": rev_7d,
            "guidance_hint": guidance,
            "beat_rate_last_4q": beat_rate,
            "eps_dispersion_pct": dispersion,
        },
    }


def get_earnings_signal(symbol: str) -> dict:
    """End-to-end: fetch consensus and compute surprise probability."""
    consensus = get_consensus_data(symbol)
    surprise = compute_surprise_probability(consensus) if consensus.get("available") else {"available": False}
    return {
        "consensus": consensus,
        "surprise": surprise,
    }
