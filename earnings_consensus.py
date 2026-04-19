"""
Earnings consensus and surprise probability. Uses yfinance's structured
estimate/history dataframes (more reliable than ticker.info dictionary).
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf
from typing import Any


def _first_float(obj, default=None):
    """Coerce a scalar or iterable to a single float; None on failure."""
    try:
        if obj is None:
            return default
        if hasattr(obj, "iloc"):
            try:
                v = obj.iloc[0]
                return float(v) if pd.notna(v) else default
            except Exception:
                pass
        if isinstance(obj, (int, float)):
            return float(obj)
        if pd.isna(obj):
            return default
        return float(obj)
    except Exception:
        return default


def _safe_df(fn):
    """Call a yfinance attribute getter that might return None / raise."""
    try:
        val = fn()
        if val is None:
            return None
        if isinstance(val, pd.DataFrame):
            return val if not val.empty else None
        return val
    except Exception:
        return None


def _extract_estimate_row(est_df: pd.DataFrame, period_key: str) -> dict | None:
    """
    Pull the current-quarter row from earnings_estimate. yfinance's index is
    typically strings like "0q" / "+1q" / "0y" / "+1y". Fall back to the first
    row if the key isn't found.
    """
    if est_df is None or est_df.empty:
        return None
    try:
        if period_key in est_df.index:
            row = est_df.loc[period_key]
        else:
            row = est_df.iloc[0]
        return row.to_dict() if hasattr(row, "to_dict") else dict(row)
    except Exception:
        return None


def get_consensus_data(symbol: str) -> dict:
    """
    Pull consensus EPS, dispersion, revisions, analyst recommendations, and
    historical beat rate for a symbol.
    """
    sym = str(symbol).upper().strip()
    try:
        t = yf.Ticker(sym)
    except Exception as e:
        return {"symbol": sym, "available": False, "error": str(e)}

    # Primary: structured estimate table (reliable).
    est_df = _safe_df(lambda: getattr(t, "earnings_estimate", None))
    trend_df = _safe_df(lambda: getattr(t, "eps_trend", None))  # yfinance >= 0.2.40
    history_df = _safe_df(lambda: getattr(t, "earnings_history", None))

    current_quarter = _extract_estimate_row(est_df, "0q") or {}
    current_eps_mean = _first_float(current_quarter.get("avg"))
    current_eps_high = _first_float(current_quarter.get("high"))
    current_eps_low = _first_float(current_quarter.get("low"))
    num_analysts = _first_float(current_quarter.get("numberOfAnalysts"))

    # Dispersion: (high - low) / |mean|
    eps_dispersion_pct = None
    if (
        current_eps_mean is not None
        and current_eps_high is not None
        and current_eps_low is not None
        and abs(current_eps_mean) > 1e-9
    ):
        eps_dispersion_pct = abs(current_eps_high - current_eps_low) / abs(current_eps_mean)

    # Revisions from eps_trend (current vs 7d/30d ago)
    eps_revision_7d_pct = None
    eps_revision_30d_pct = None
    if trend_df is not None and not trend_df.empty:
        try:
            trend_row = trend_df.loc["0q"] if "0q" in trend_df.index else trend_df.iloc[0]
            current = _first_float(trend_row.get("current"))
            days_7 = _first_float(trend_row.get("7daysAgo"))
            days_30 = _first_float(trend_row.get("30daysAgo"))
            if current is not None and days_7 is not None and abs(days_7) > 1e-9:
                eps_revision_7d_pct = (current - days_7) / abs(days_7)
            if current is not None and days_30 is not None and abs(days_30) > 1e-9:
                eps_revision_30d_pct = (current - days_30) / abs(days_30)
        except Exception:
            pass

    # Historical beat rate from earnings_history
    beats = 0
    total_q = 0
    if history_df is not None and not history_df.empty:
        try:
            for _, row in history_df.tail(4).iterrows():
                actual = _first_float(row.get("epsActual"))
                estimate = _first_float(row.get("epsEstimate"))
                if actual is not None and estimate is not None:
                    total_q += 1
                    if actual > estimate:
                        beats += 1
        except Exception:
            pass
    beat_rate_last_4q = beats / total_q if total_q else None

    # Guidance hint via recommendation key
    info = {}
    try:
        info = t.info or {}
    except Exception:
        info = {}
    rec_key = str(info.get("recommendationKey") or "").lower()
    if rec_key in {"strong_buy", "buy"}:
        guidance_hint = "above_consensus"
    elif rec_key in {"sell", "strong_sell", "underperform"}:
        guidance_hint = "below_consensus"
    else:
        guidance_hint = "in_line"

    # Earnings date
    earnings_date = None
    try:
        cal = _safe_df(lambda: t.calendar)
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if isinstance(ed, list) and ed:
                earnings_date = str(ed[0])[:10]
            elif ed:
                earnings_date = str(ed)[:10]
        elif isinstance(cal, pd.DataFrame) and not cal.empty:
            for row_name in cal.index:
                if "earnings" in str(row_name).lower():
                    v = cal.loc[row_name]
                    v0 = v.iloc[0] if hasattr(v, "iloc") else v
                    if hasattr(v0, "strftime"):
                        earnings_date = v0.strftime("%Y-%m-%d")
                    else:
                        earnings_date = str(v0)[:10]
                    break
    except Exception:
        pass
    if earnings_date is None:
        try:
            ts = info.get("earningsTimestamp")
            if ts:
                from datetime import datetime, timezone
                earnings_date = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            pass

    return {
        "symbol": sym,
        "available": True,
        "consensus_eps": current_eps_mean,
        "eps_high": current_eps_high,
        "eps_low": current_eps_low,
        "eps_dispersion_pct": round(eps_dispersion_pct, 3) if eps_dispersion_pct is not None else None,
        "eps_revision_7d_pct": round(eps_revision_7d_pct, 4) if eps_revision_7d_pct is not None else None,
        "eps_revision_30d_pct": round(eps_revision_30d_pct, 4) if eps_revision_30d_pct is not None else None,
        "analyst_count": int(num_analysts) if num_analysts else None,
        "guidance_hint": guidance_hint,
        "earnings_date": earnings_date,
        "beat_rate_last_4q": round(beat_rate_last_4q, 2) if beat_rate_last_4q is not None else None,
        "quarters_analyzed": total_q,
        "data_sources": {
            "earnings_estimate_available": est_df is not None,
            "eps_trend_available": trend_df is not None,
            "earnings_history_available": history_df is not None,
        },
    }


def compute_surprise_probability(consensus: dict) -> dict:
    """
    Apply the heuristic model from the earnings-surprise-modeler skill, with
    explicit reasoning for which inputs were actually usable.
    """
    if not consensus or not consensus.get("available"):
        return {"available": False}

    p = 0.5
    reasoning = []

    rev_30d = consensus.get("eps_revision_30d_pct")
    rev_7d = consensus.get("eps_revision_7d_pct")

    if rev_30d is not None:
        if rev_30d > 0.02:
            p += 0.10
            reasoning.append(f"30d revisions +{rev_30d:.3f} → +0.10")
        elif rev_30d < -0.02:
            p -= 0.10
            reasoning.append(f"30d revisions {rev_30d:.3f} → −0.10")

    if rev_7d is not None and rev_30d is not None and rev_7d > 0.01 and rev_30d > 0.01:
        p += 0.05
        reasoning.append("Revisions accelerating into print → +0.05")

    guidance = consensus.get("guidance_hint")
    if guidance == "above_consensus":
        p += 0.05
        reasoning.append("Analyst recs favor beat → +0.05")
    elif guidance == "below_consensus":
        p -= 0.05
        reasoning.append("Analyst recs favor miss → −0.05")

    beat_rate = consensus.get("beat_rate_last_4q")
    if beat_rate is not None:
        if beat_rate >= 0.75:
            p += 0.05
            reasoning.append(f"History beat_rate {beat_rate} → +0.05")
        elif beat_rate <= 0.25:
            p -= 0.05
            reasoning.append(f"History beat_rate {beat_rate} → −0.05")

    p = max(0.10, min(0.90, p))

    # Confidence reflects how many inputs we actually had
    usable_inputs = sum(
        1 for v in (rev_30d, rev_7d, guidance != "in_line", beat_rate) if v not in (None, False)
    )
    dispersion = consensus.get("eps_dispersion_pct")
    if dispersion is not None and dispersion > 0.25:
        confidence = "low"
    elif usable_inputs >= 3:
        confidence = "high"
    elif usable_inputs >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "available": True,
        "surprise_probability": round(p, 3),
        "confidence": confidence,
        "usable_input_count": usable_inputs,
        "reasoning": reasoning,
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
