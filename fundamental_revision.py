"""Fundamental estimate revision and earnings-quality signal."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import yfinance as yf


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if hasattr(value, "iloc"):
            value = value.iloc[0]
        if value in ("", None):
            return default
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_df(value: Any) -> pd.DataFrame | None:
    try:
        if value is None:
            return None
        if callable(value):
            value = value()
        if isinstance(value, pd.DataFrame) and not value.empty:
            return value
        return None
    except Exception:
        return None


def _first_available_df(*values: Any) -> pd.DataFrame | None:
    for value in values:
        df = _safe_df(value)
        if df is not None:
            return df
    return None


def _row(df: pd.DataFrame | None, key: str) -> dict:
    if df is None or df.empty:
        return {}
    try:
        if key in df.index:
            row = df.loc[key]
        else:
            row = df.iloc[0]
        return row.to_dict() if hasattr(row, "to_dict") else dict(row)
    except Exception:
        return {}


def _latest_line_item(df: pd.DataFrame | None, labels: tuple[str, ...]) -> float | None:
    if df is None or df.empty:
        return None
    normalized = {str(idx).strip().lower(): idx for idx in df.index}
    for label in labels:
        idx = normalized.get(label.strip().lower())
        if idx is None:
            continue
        try:
            series = df.loc[idx]
            if hasattr(series, "dropna"):
                series = series.dropna()
            if len(series) == 0:
                return None
            return _to_float(series.iloc[0])
        except Exception:
            continue
    return None


def _pct_change(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or abs(prior) < 1e-9:
        return None
    return (current - prior) / abs(prior)


def _revision_points(revisions: dict) -> tuple[float, list[str]]:
    points = 0.0
    reasons: list[str] = []

    rev_30d = revisions.get("eps_revision_30d_pct")
    if rev_30d is not None:
        if rev_30d >= 0.05:
            points += 30
            reasons.append("30d EPS revisions strongly positive")
        elif rev_30d >= 0.02:
            points += 20
            reasons.append("30d EPS revisions positive")
        elif rev_30d > 0:
            points += 10
            reasons.append("30d EPS revisions slightly positive")
        elif rev_30d <= -0.05:
            points -= 30
            reasons.append("30d EPS revisions strongly negative")
        elif rev_30d <= -0.02:
            points -= 20
            reasons.append("30d EPS revisions negative")
        elif rev_30d < 0:
            points -= 10
            reasons.append("30d EPS revisions slightly negative")

    rev_7d = revisions.get("eps_revision_7d_pct")
    if rev_7d is not None and rev_30d is not None:
        if rev_7d > 0.01 and rev_30d > 0:
            points += 10
            reasons.append("EPS revisions accelerating over 7d")
        elif rev_7d < -0.01 and rev_30d < 0:
            points -= 10
            reasons.append("EPS revisions deteriorating over 7d")

    rev_90d = revisions.get("eps_revision_90d_pct")
    if rev_90d is not None:
        if rev_90d > 0.05:
            points += 10
            reasons.append("90d EPS trend positive")
        elif rev_90d < -0.05:
            points -= 10
            reasons.append("90d EPS trend negative")

    breadth = revisions.get("revision_breadth_30d")
    if breadth is not None:
        points += 20 * _clamp(float(breadth), -1.0, 1.0)
        if breadth >= 0.5:
            reasons.append("analyst revision breadth positive")
        elif breadth <= -0.5:
            reasons.append("analyst revision breadth negative")

    dispersion = revisions.get("eps_dispersion_pct")
    if dispersion is not None:
        if dispersion > 0.40:
            points -= 25
            reasons.append("analyst EPS dispersion very high")
        elif dispersion > 0.25:
            points -= 15
            reasons.append("analyst EPS dispersion high")

    return _clamp(points, -100, 100), reasons


def _quality_points(quality: dict) -> tuple[float, list[str]]:
    points = 0.0
    reasons: list[str] = []

    cfo_ni = quality.get("cfo_to_net_income")
    if cfo_ni is not None:
        if cfo_ni >= 1.1:
            points += 25
            reasons.append("cash conversion above earnings")
        elif cfo_ni >= 0.8:
            points += 10
            reasons.append("cash conversion acceptable")
        elif cfo_ni >= 0:
            points -= 20
            reasons.append("cash conversion weak")

    accruals = quality.get("accruals_to_assets")
    if accruals is not None:
        if accruals <= 0:
            points += 20
            reasons.append("negative accruals support earnings quality")
        elif accruals <= 0.05:
            points += 8
            reasons.append("low accruals")
        elif accruals >= 0.10:
            points -= 20
            reasons.append("high accruals weaken earnings quality")

    fcf_margin = quality.get("free_cash_flow_margin")
    if fcf_margin is not None:
        if fcf_margin >= 0.10:
            points += 15
            reasons.append("healthy free-cash-flow margin")
        elif fcf_margin < 0:
            points -= 15
            reasons.append("negative free-cash-flow margin")

    buyback_ratio = quality.get("buyback_to_net_income")
    if buyback_ratio is not None:
        if buyback_ratio >= 0.05:
            points += 5
            reasons.append("buybacks support per-share economics")
        elif buyback_ratio <= -0.10:
            points -= 5
            reasons.append("share issuance/dilution pressure")

    return _clamp(points, -100, 100), reasons


def score_fundamental_revision_signal(revisions: dict, quality: dict) -> dict:
    """Score an already-normalized revision/quality payload."""
    revision_score, revision_reasons = _revision_points(revisions)
    quality_score, quality_reasons = _quality_points(quality)
    combined = _clamp((0.65 * revision_score) + (0.35 * quality_score), -100, 100)

    usable_fields = sum(
        1
        for value in [
            revisions.get("eps_revision_7d_pct"),
            revisions.get("eps_revision_30d_pct"),
            revisions.get("eps_revision_90d_pct"),
            revisions.get("revision_breadth_30d"),
            revisions.get("eps_dispersion_pct"),
            quality.get("cfo_to_net_income"),
            quality.get("accruals_to_assets"),
            quality.get("free_cash_flow_margin"),
            quality.get("buyback_to_net_income"),
        ]
        if value is not None
    )
    analyst_count = revisions.get("analyst_count") or 0
    dispersion = revisions.get("eps_dispersion_pct")
    if usable_fields >= 6 and analyst_count >= 6 and (dispersion is None or dispersion <= 0.25):
        confidence = "high"
    elif usable_fields >= 4 and analyst_count >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    if combined >= 25:
        label = "bullish"
    elif combined <= -25:
        label = "bearish"
    else:
        label = "neutral"

    veto = combined <= -35 or (revisions.get("eps_revision_30d_pct") is not None and revisions["eps_revision_30d_pct"] <= -0.05)
    return {
        "available": usable_fields > 0,
        "fundamental_revision_score": round(combined, 1),
        "revision_score": round(revision_score, 1),
        "quality_score": round(quality_score, 1),
        "signal": label,
        "confidence": confidence,
        "usable_field_count": usable_fields,
        "negative_revision_veto": bool(veto),
        "reasoning": revision_reasons + quality_reasons,
    }


def get_fundamental_revision_signal(symbol: str) -> dict:
    """Fetch estimates/financial statements and compute the revision-quality signal."""
    sym = str(symbol or "").upper().strip()
    if not sym:
        return {"symbol": sym, "available": False, "error": "symbol is required"}

    try:
        ticker = yf.Ticker(sym)
    except Exception as exc:
        return {"symbol": sym, "available": False, "error": str(exc)}

    est_df = _safe_df(lambda: getattr(ticker, "earnings_estimate", None))
    trend_df = _safe_df(lambda: getattr(ticker, "eps_trend", None))
    rev_df = _safe_df(lambda: getattr(ticker, "eps_revisions", None))
    revenue_df = _safe_df(lambda: getattr(ticker, "revenue_estimate", None))
    cashflow = _first_available_df(
        lambda: getattr(ticker, "quarterly_cashflow", None),
        lambda: getattr(ticker, "cashflow", None),
    )
    financials = _first_available_df(
        lambda: getattr(ticker, "quarterly_financials", None),
        lambda: getattr(ticker, "financials", None),
    )
    balance = _first_available_df(
        lambda: getattr(ticker, "quarterly_balance_sheet", None),
        lambda: getattr(ticker, "balance_sheet", None),
    )

    est_row = _row(est_df, "0q")
    trend_row = _row(trend_df, "0q")
    rev_row = _row(rev_df, "0q")
    revenue_row = _row(revenue_df, "0q")

    eps_current = _to_float(trend_row.get("current"))
    eps_7 = _to_float(trend_row.get("7daysAgo"))
    eps_30 = _to_float(trend_row.get("30daysAgo"))
    eps_90 = _to_float(trend_row.get("90daysAgo"))
    eps_mean = _to_float(est_row.get("avg"))
    eps_high = _to_float(est_row.get("high"))
    eps_low = _to_float(est_row.get("low"))
    analyst_count = _to_float(est_row.get("numberOfAnalysts"))

    dispersion = None
    if eps_mean is not None and eps_high is not None and eps_low is not None and abs(eps_mean) > 1e-9:
        dispersion = abs(eps_high - eps_low) / abs(eps_mean)

    up_30 = _to_float(rev_row.get("upLast30days"), 0.0)
    down_30 = _to_float(rev_row.get("downLast30days"), 0.0)
    breadth = None
    if up_30 is not None and down_30 is not None and up_30 + down_30 > 0:
        breadth = (up_30 - down_30) / (up_30 + down_30)

    revenue_growth = _to_float(revenue_row.get("growth"))

    operating_cash_flow = _latest_line_item(
        cashflow,
        ("Operating Cash Flow", "Total Cash From Operating Activities"),
    )
    capital_expenditure = _latest_line_item(cashflow, ("Capital Expenditure", "Capital Expenditures"))
    buyback_raw = _latest_line_item(
        cashflow,
        ("Repurchase Of Capital Stock", "Repurchase of Capital Stock", "Common Stock Repurchased"),
    )
    net_income = _latest_line_item(financials, ("Net Income", "Net Income Common Stockholders"))
    total_revenue = _latest_line_item(financials, ("Total Revenue", "Operating Revenue"))
    total_assets = _latest_line_item(balance, ("Total Assets",))

    free_cash_flow = None
    if operating_cash_flow is not None:
        free_cash_flow = operating_cash_flow + (capital_expenditure or 0.0)

    cfo_to_net_income = None
    if operating_cash_flow is not None and net_income is not None and abs(net_income) > 1e-9:
        cfo_to_net_income = operating_cash_flow / net_income

    accruals_to_assets = None
    if net_income is not None and operating_cash_flow is not None and total_assets is not None and abs(total_assets) > 1e-9:
        accruals_to_assets = (net_income - operating_cash_flow) / total_assets

    free_cash_flow_margin = None
    if free_cash_flow is not None and total_revenue is not None and abs(total_revenue) > 1e-9:
        free_cash_flow_margin = free_cash_flow / total_revenue

    buyback_to_net_income = None
    if buyback_raw is not None and net_income is not None and abs(net_income) > 1e-9:
        buyback_to_net_income = abs(buyback_raw) / abs(net_income) if buyback_raw < 0 else -abs(buyback_raw) / abs(net_income)

    revisions = {
        "eps_revision_7d_pct": _pct_change(eps_current, eps_7),
        "eps_revision_30d_pct": _pct_change(eps_current, eps_30),
        "eps_revision_90d_pct": _pct_change(eps_current, eps_90),
        "revision_breadth_30d": breadth,
        "eps_dispersion_pct": dispersion,
        "analyst_count": int(analyst_count) if analyst_count else None,
        "revenue_growth_estimate": revenue_growth,
    }
    quality = {
        "cfo_to_net_income": cfo_to_net_income,
        "accruals_to_assets": accruals_to_assets,
        "free_cash_flow_margin": free_cash_flow_margin,
        "buyback_to_net_income": buyback_to_net_income,
        "operating_cash_flow": operating_cash_flow,
        "net_income": net_income,
        "free_cash_flow": free_cash_flow,
        "total_assets": total_assets,
    }
    rounded_revisions = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in revisions.items()}
    rounded_quality = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in quality.items()}
    score = score_fundamental_revision_signal(rounded_revisions, rounded_quality)
    text = (
        f"{sym} fundamental revisions: score={score['fundamental_revision_score']} "
        f"signal={score['signal']} confidence={score['confidence']}"
    )
    if score.get("negative_revision_veto"):
        text += " | negative revision veto"

    return {
        "symbol": sym,
        **score,
        "revisions": rounded_revisions,
        "earnings_quality": rounded_quality,
        "data_quality": {
            "source": "yfinance_estimates_and_financials",
            "fetched_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "estimate_tables": {
                "earnings_estimate": est_df is not None,
                "eps_trend": trend_df is not None,
                "eps_revisions": rev_df is not None,
                "revenue_estimate": revenue_df is not None,
                "cashflow": cashflow is not None,
                "financials": financials is not None,
                "balance_sheet": balance is not None,
            },
        },
        "result_text": text,
    }
