"""
Advanced quant: Fama-French 5-factor attribution, VaR/CVaR, mean-variance
optimization (simplified), Kelly sizing, risk-parity weights, position-level
risk attribution.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


# Factor ETF proxies (free, tradable, daily-updating)
# These are not the exact Ken French factors but are the best free liquid proxies.
FACTOR_PROXIES = {
    "MKT": "SPY",          # Market
    "SMB": "IWM",          # Small minus Big (approx via Russell 2000)
    "HML": "VTV",          # Value (Vanguard Value ETF)
    "QMJ": "QUAL",         # Quality minus Junk
    "MOM": "MTUM",         # Momentum
}


def _download_returns(symbols: list[str], period: str = "1y") -> pd.DataFrame:
    """Download daily returns for a set of symbols."""
    try:
        data = yf.download(symbols, period=period, progress=False, auto_adjust=True)
        if data is None or data.empty:
            return pd.DataFrame()
        if isinstance(data.columns, pd.MultiIndex):
            close = data["Close"] if "Close" in data.columns.get_level_values(0) else data
        else:
            close = data
        if isinstance(close, pd.Series):
            close = close.to_frame(name=symbols[0] if symbols else "Close")
        return close.pct_change().dropna(how="all")
    except Exception:
        return pd.DataFrame()


def _regress_ols(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, float]:
    """Manual OLS regression. Returns (betas, r_squared). X should include intercept column."""
    try:
        betas, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)
        y_hat = X @ betas
        ss_res = np.sum((y - y_hat) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        return betas, float(r2)
    except Exception:
        return np.array([]), 0.0


def compute_factor_attribution(symbol: str, period: str = "1y") -> dict:
    """
    Regress a symbol's returns against 5-factor ETF proxies.
    Returns factor loadings and R^2.
    """
    factor_symbols = list(FACTOR_PROXIES.values())
    all_symbols = [symbol.upper()] + factor_symbols
    returns = _download_returns(all_symbols, period=period)
    if returns.empty or symbol.upper() not in returns.columns:
        return {"available": False, "reason": "insufficient_data"}

    returns = returns.dropna()
    if len(returns) < 60:
        return {"available": False, "reason": "insufficient_history"}

    y = returns[symbol.upper()].values
    X_cols = []
    factor_names = []
    for name, proxy in FACTOR_PROXIES.items():
        if proxy not in returns.columns:
            continue
        if name == "SMB":
            # Small minus Big: IWM - SPY
            if "SPY" in returns.columns:
                X_cols.append((returns[proxy] - returns["SPY"]).values)
                factor_names.append(name)
        elif name == "HML":
            # Value minus Growth: VTV - VUG. Approximate with VTV - SPY if VUG absent
            X_cols.append((returns[proxy] - returns["SPY"]).values if "SPY" in returns.columns else returns[proxy].values)
            factor_names.append(name)
        elif name == "MKT":
            # Raw market return
            X_cols.append(returns[proxy].values)
            factor_names.append(name)
        else:
            # QMJ, MOM: use raw factor ETF return (not pure long-short, but directionally useful)
            X_cols.append(returns[proxy].values)
            factor_names.append(name)

    if not X_cols:
        return {"available": False, "reason": "no_factor_proxies_available"}

    X = np.column_stack([np.ones(len(y))] + X_cols)
    betas, r2 = _regress_ols(y, X)
    if len(betas) == 0:
        return {"available": False, "reason": "regression_failed"}

    alpha_daily = float(betas[0])
    alpha_annual = alpha_daily * 252
    factor_betas = {name: round(float(b), 3) for name, b in zip(factor_names, betas[1:])}

    return {
        "available": True,
        "symbol": symbol.upper(),
        "period": period,
        "samples": len(returns),
        "alpha_daily": round(alpha_daily, 6),
        "alpha_annual_pct": round(alpha_annual * 100, 3),
        "factor_betas": factor_betas,
        "r_squared": round(r2, 3),
        "factors_used": factor_names,
        "proxy_mapping": FACTOR_PROXIES,
    }


def compute_var_cvar(
    positions: list[dict],
    confidence: float = 0.95,
    horizon_days: int = 1,
    period: str = "1y",
) -> dict:
    """
    Historical-simulation VaR and CVaR for a portfolio.

    Args:
        positions: [{symbol, market_value_usd}, ...]
        confidence: e.g., 0.95 for 95% VaR
        horizon_days: 1, 5, 20
    """
    if not positions:
        return {"available": False, "reason": "no_positions"}

    symbols = [p["symbol"].upper() for p in positions if p.get("symbol")]
    weights = np.array([float(p.get("market_value_usd") or 0) for p in positions])
    total = weights.sum()
    if total <= 0:
        return {"available": False, "reason": "zero_portfolio"}
    weights = weights / total

    returns = _download_returns(symbols, period=period)
    if returns.empty or len(returns) < 30:
        return {"available": False, "reason": "insufficient_returns"}

    # Align columns to weights
    aligned_symbols = [s for s in symbols if s in returns.columns]
    if len(aligned_symbols) != len(symbols):
        # Re-normalize to the subset we actually have data for
        idx = [symbols.index(s) for s in aligned_symbols]
        weights = weights[idx]
        weights = weights / weights.sum() if weights.sum() > 0 else weights
    returns = returns[aligned_symbols].dropna()

    portfolio_returns = returns.values @ weights

    # Scale to horizon: sqrt(T) for volatility, but historical sim uses rolling sums
    if horizon_days > 1:
        rolling_sum = pd.Series(portfolio_returns).rolling(horizon_days).sum().dropna().values
        portfolio_returns = rolling_sum

    q = 1 - confidence
    var = -np.quantile(portfolio_returns, q)
    tail = portfolio_returns[portfolio_returns <= np.quantile(portfolio_returns, q)]
    cvar = -tail.mean() if len(tail) > 0 else var

    return {
        "available": True,
        "confidence": confidence,
        "horizon_days": horizon_days,
        "var_pct": round(float(var) * 100, 3),
        "cvar_pct": round(float(cvar) * 100, 3),
        "var_usd": round(float(var) * total, 2),
        "cvar_usd": round(float(cvar) * total, 2),
        "portfolio_value_usd": round(total, 2),
        "samples": len(portfolio_returns),
        "method": "historical_simulation",
    }


def kelly_sizing(
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    kelly_fraction: float = 0.25,
) -> dict:
    """
    Fractional Kelly sizing. Default uses quarter-Kelly for safety (recommended
    in practice since edge estimates are noisy).

    Returns a recommended position size as fraction of equity.
    """
    if avg_loss_pct <= 0 or avg_win_pct <= 0:
        return {"available": False, "reason": "invalid_inputs"}

    b = avg_win_pct / avg_loss_pct  # payoff ratio
    p = max(0.0, min(1.0, win_rate))
    q = 1 - p
    full_kelly = (b * p - q) / b if b > 0 else 0
    suggested = max(0.0, full_kelly * kelly_fraction)

    return {
        "available": True,
        "full_kelly_fraction": round(full_kelly, 4),
        "kelly_multiplier": kelly_fraction,
        "suggested_position_pct": round(suggested * 100, 2),
        "payoff_ratio": round(b, 3),
        "inputs": {"win_rate": p, "avg_win_pct": avg_win_pct, "avg_loss_pct": avg_loss_pct},
        "note": "Quarter-Kelly (0.25x) recommended; full Kelly too aggressive given edge uncertainty",
    }


def risk_parity_weights(symbols: list[str], period: str = "1y") -> dict:
    """
    Compute inverse-volatility (naive risk parity) weights.
    Real risk parity requires iterative equal-risk-contribution; this is
    the simpler inverse-vol approximation (close enough for most uses).
    """
    returns = _download_returns(symbols, period=period)
    if returns.empty:
        return {"available": False, "reason": "no_data"}

    vol = returns.std() * math.sqrt(252)
    inv_vol = 1.0 / vol
    weights = inv_vol / inv_vol.sum()
    return {
        "available": True,
        "weights": {sym: round(float(w), 4) for sym, w in weights.items()},
        "annualized_volatilities": {sym: round(float(v), 4) for sym, v in vol.items()},
        "method": "inverse_volatility",
    }


def mean_variance_weights(
    symbols: list[str],
    risk_aversion: float = 3.0,
    period: str = "1y",
) -> dict:
    """
    Simple mean-variance optimizer (no short-sales, no constraints beyond
    sum=1). Uses risk-aversion parameter λ; higher λ = more conservative.
    """
    returns = _download_returns(symbols, period=period)
    if returns.empty:
        return {"available": False, "reason": "no_data"}

    returns = returns.dropna()
    mu = returns.mean().values * 252
    cov = returns.cov().values * 252
    n = len(symbols)

    # Analytical MV (tangency-adjusted) with λ: w = (1/λ) * Σ^-1 * μ, normalized to sum 1
    try:
        inv_cov = np.linalg.pinv(cov)
        w_unnorm = (inv_cov @ mu) / max(risk_aversion, 1e-6)
        # Project to non-negative and re-normalize
        w_unnorm = np.maximum(w_unnorm, 0)
        s = w_unnorm.sum()
        if s <= 0:
            # Fall back to equal-weight if all-negative
            w = np.ones(n) / n
        else:
            w = w_unnorm / s
    except Exception:
        w = np.ones(n) / n

    expected_return_annual = float(w @ mu)
    portfolio_var = float(w @ cov @ w)
    portfolio_vol = math.sqrt(max(0.0, portfolio_var))

    return {
        "available": True,
        "weights": {sym: round(float(wi), 4) for sym, wi in zip(symbols, w)},
        "risk_aversion": risk_aversion,
        "expected_annual_return_pct": round(expected_return_annual * 100, 3),
        "expected_annual_vol_pct": round(portfolio_vol * 100, 3),
        "expected_sharpe": round(expected_return_annual / portfolio_vol, 3) if portfolio_vol > 0 else None,
        "method": "mean_variance_long_only",
    }


def position_risk_attribution(positions: list[dict], period: str = "6mo") -> dict:
    """
    For each position, compute:
      - dollar weight
      - contribution to portfolio volatility (marginal risk)
      - correlation with the rest of the portfolio
    """
    if not positions:
        return {"available": False}

    symbols = [p["symbol"].upper() for p in positions if p.get("symbol")]
    weights = np.array([float(p.get("market_value_usd") or 0) for p in positions])
    total = weights.sum()
    if total <= 0:
        return {"available": False}
    w = weights / total

    returns = _download_returns(symbols, period=period)
    if returns.empty:
        return {"available": False}

    returns = returns.dropna()
    aligned = [s for s in symbols if s in returns.columns]
    if len(aligned) != len(symbols):
        idx = [symbols.index(s) for s in aligned]
        w = w[idx]
        w = w / w.sum() if w.sum() > 0 else w
    returns = returns[aligned]

    cov = returns.cov().values * 252
    portfolio_var = float(w @ cov @ w)
    portfolio_vol = math.sqrt(max(0.0, portfolio_var))

    # Marginal contribution to risk: w_i * (Σ w)_i / σ_p
    marginal = cov @ w
    rc = w * marginal
    pct_of_var = rc / portfolio_var if portfolio_var > 0 else np.zeros_like(rc)

    # Correlation of each position with the portfolio
    port_ret = returns.values @ w
    corrs = []
    for i, sym in enumerate(aligned):
        x = returns[sym].values
        if np.std(x) > 0 and np.std(port_ret) > 0:
            corr = float(np.corrcoef(x, port_ret)[0, 1])
        else:
            corr = 0.0
        corrs.append(corr)

    rows = []
    for i, sym in enumerate(aligned):
        rows.append({
            "symbol": sym,
            "weight": round(float(w[i]), 4),
            "pct_of_portfolio_variance": round(float(pct_of_var[i]), 4),
            "correlation_with_portfolio": round(corrs[i], 3),
        })

    rows.sort(key=lambda r: r["pct_of_portfolio_variance"], reverse=True)

    concentration_flag = None
    if rows and rows[0]["pct_of_portfolio_variance"] > 0.40:
        concentration_flag = {
            "symbol": rows[0]["symbol"],
            "pct_of_portfolio_variance": rows[0]["pct_of_portfolio_variance"],
            "warning": "single_position_dominates_risk",
        }

    return {
        "available": True,
        "positions": rows,
        "portfolio_volatility_annual_pct": round(portfolio_vol * 100, 3),
        "concentration_flag": concentration_flag,
    }
