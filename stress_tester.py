"""
Historical shock replay for portfolio stress testing. Uses β-weighted factor
moves to approximate portfolio P&L under named historical scenarios.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf
from typing import Any


# Historical shock catalog. Factor moves are representative (not exact windows).
# Sector ETF returns are illustrative regime moves.
SHOCK_CATALOG = {
    "covid_2020_03": {
        "window_days": 22,
        "description": "COVID crash Feb 19 - Mar 23, 2020",
        "factor_moves": {
            "SPY": -0.32, "QQQ": -0.30, "IWM": -0.41,
            "XLK": -0.24, "XLF": -0.43, "XLE": -0.51, "XLV": -0.20,
            "XLI": -0.35, "XLC": -0.26, "XLY": -0.30, "XLP": -0.15,
            "XLU": -0.32, "XLRE": -0.40,
            "HYG": -0.18, "TLT": +0.18, "GLD": +0.03, "DBC": -0.35,
        },
        "recovery_days_historical": 148,
    },
    "volmageddon_2018_02": {
        "window_days": 9,
        "description": "Feb 2018 vol spike / XIV blowup",
        "factor_moves": {
            "SPY": -0.10, "QQQ": -0.11, "IWM": -0.09,
            "XLK": -0.11, "XLF": -0.11, "XLE": -0.12,
        },
        "recovery_days_historical": 142,
    },
    "rate_shock_2022": {
        "window_days": 210,
        "description": "2022 rate hikes; growth / duration compression",
        "factor_moves": {
            "SPY": -0.25, "QQQ": -0.33, "IWM": -0.22,
            "XLK": -0.28, "XLF": -0.12, "XLE": +0.62, "XLV": -0.04,
            "XLI": -0.08, "XLC": -0.39, "XLY": -0.37, "XLP": -0.03,
            "XLU": -0.01, "XLRE": -0.27,
            "HYG": -0.11, "TLT": -0.31,
        },
        "recovery_days_historical": 400,
    },
    "banking_2023_03": {
        "window_days": 10,
        "description": "SVB / regional bank stress",
        "factor_moves": {
            "SPY": -0.03, "QQQ": +0.02, "IWM": -0.07,
            "XLF": -0.12, "KRE": -0.30, "XLK": +0.04,
        },
        "recovery_days_historical": 90,
    },
    "gfc_2008_09": {
        "window_days": 30,
        "description": "Sep-Oct 2008 GFC acute phase",
        "factor_moves": {
            "SPY": -0.28, "QQQ": -0.29, "IWM": -0.30,
            "XLF": -0.35, "XLE": -0.30, "XLK": -0.27,
            "HYG": -0.22, "TLT": +0.05, "GLD": -0.10,
        },
        "recovery_days_historical": 400,
    },
    "inflation_surprise_hypo": {
        "window_days": 20,
        "description": "Hypothetical: +100bp 10Y in 30 days",
        "factor_moves": {
            "SPY": -0.08, "QQQ": -0.15, "IWM": -0.10,
            "XLK": -0.15, "XLF": +0.02, "XLE": +0.08, "XLU": -0.08, "XLRE": -0.12,
            "TLT": -0.12, "GLD": -0.06,
        },
        "recovery_days_historical": None,
    },
    "ai_bubble_unwind_hypo": {
        "window_days": 30,
        "description": "Hypothetical: AI-exposed names sell off",
        "factor_moves": {
            "SPY": -0.10, "QQQ": -0.20, "IWM": -0.05,
            "XLK": -0.25, "XLC": -0.20, "XLV": -0.02, "XLP": -0.01,
        },
        "recovery_days_historical": None,
    },
}


def _download_close(symbols: list[str], period: str = "1y") -> pd.DataFrame:
    try:
        data = yf.download(symbols, period=period, progress=False, auto_adjust=True)
        if data is None or data.empty:
            return pd.DataFrame()
        if isinstance(data.columns, pd.MultiIndex):
            close = data["Close"] if "Close" in data.columns.get_level_values(0) else data
        else:
            close = data
        if isinstance(close, pd.Series):
            close = close.to_frame(name=symbols[0])
        return close.dropna(how="all")
    except Exception:
        return pd.DataFrame()


def _beta_to_spy(symbol: str, period: str = "1y") -> float | None:
    """Compute β of symbol vs SPY."""
    try:
        data = _download_close([symbol, "SPY"], period=period)
        if data.empty or symbol not in data.columns or "SPY" not in data.columns:
            return None
        r = data.pct_change().dropna()
        if len(r) < 30:
            return None
        cov = r[symbol].cov(r["SPY"])
        var = r["SPY"].var()
        if var <= 0:
            return None
        return float(cov / var)
    except Exception:
        return None


def replay_shock(positions: list[dict], shock_name: str) -> dict:
    """
    Replay a named shock against a portfolio.

    positions: [{symbol, market_value_usd}, ...]
    """
    shock = SHOCK_CATALOG.get(shock_name)
    if not shock:
        return {
            "available": False,
            "reason": "unknown_shock",
            "known_shocks": list(SHOCK_CATALOG.keys()),
        }

    if not positions:
        return {"available": False, "reason": "no_positions"}

    moves = shock["factor_moves"]
    total = sum(float(p.get("market_value_usd") or 0) for p in positions)
    if total <= 0:
        return {"available": False, "reason": "zero_portfolio"}

    details = []
    total_pnl_usd = 0.0

    for pos in positions:
        sym = (pos.get("symbol") or "").upper()
        mv = float(pos.get("market_value_usd") or 0)
        if not sym or mv <= 0:
            continue

        # Direct factor match?
        direct_move = moves.get(sym)
        source = "direct"
        if direct_move is None:
            # β-to-SPY fallback
            beta = _beta_to_spy(sym)
            spy_move = moves.get("SPY")
            if beta is None or spy_move is None:
                # Conservative default: assume SPY-like exposure
                beta = 1.0
                source = "default_beta_1.0"
            else:
                source = f"beta_scaled_{beta:.2f}"
            direct_move = (spy_move or 0) * beta

        pnl_usd = mv * direct_move
        total_pnl_usd += pnl_usd
        details.append({
            "symbol": sym,
            "weight": round(mv / total, 4),
            "expected_move_pct": round(direct_move, 4),
            "expected_pnl_usd": round(pnl_usd, 2),
            "contribution_pct": round(pnl_usd / total, 4),
            "source": source,
        })

    details.sort(key=lambda r: r["expected_pnl_usd"])
    worst_positions = details[:3]
    best_positions = list(reversed(details[-3:]))

    return {
        "available": True,
        "shock_name": shock_name,
        "description": shock["description"],
        "window_days": shock["window_days"],
        "portfolio_value_usd": round(total, 2),
        "expected_pnl_usd": round(total_pnl_usd, 2),
        "expected_pnl_pct": round(total_pnl_usd / total, 4),
        "worst_positions": worst_positions,
        "best_positions": best_positions,
        "recovery_days_historical": shock.get("recovery_days_historical"),
        "note": "Linear beta model — real tails often 1.3-2x more severe",
    }


def replay_all_shocks(positions: list[dict]) -> dict:
    """Run all catalog shocks and summarize."""
    results = {}
    for name in SHOCK_CATALOG:
        r = replay_shock(positions, name)
        if r.get("available"):
            results[name] = {
                "pnl_pct": r["expected_pnl_pct"],
                "pnl_usd": r["expected_pnl_usd"],
                "description": r["description"],
            }

    if not results:
        return {"available": False}

    worst_name = min(results, key=lambda k: results[k]["pnl_pct"])
    median_pnl = float(np.median([v["pnl_pct"] for v in results.values()]))

    return {
        "available": True,
        "scenarios": results,
        "worst_case_scenario": worst_name,
        "worst_case_pnl_pct": results[worst_name]["pnl_pct"],
        "median_scenario_pnl_pct": round(median_pnl, 4),
    }
