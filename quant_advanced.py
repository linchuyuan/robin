"""
Advanced quant: Fama-French 5-factor attribution, VaR/CVaR, mean-variance
optimization (simplified), Kelly sizing, risk-parity weights, position-level
risk attribution.

Factor model uses Ken French's published daily FF5+MOM data when available
(free CSV), with Tikhonov-regularized OLS. Falls back to ETF proxies when the
Ken French server is unreachable.
"""
from __future__ import annotations

import io
import math
import os
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


# Ken French daily factor data URLs (free, stable CSV endpoints)
_KF_FF5_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
_KF_MOM_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip"
_MEMORY_DIR = Path(os.getenv("CLAWD_MEMORY_DIR", str(Path(__file__).parent / "memory"))).expanduser()
_KF_CACHE_DIR = Path(os.getenv("ROBIN_KF_CACHE_DIR", str(_MEMORY_DIR / "ken_french")))
_KF_CACHE_TTL_HOURS = 24
_RIDGE_LAMBDA = 1e-3  # Tikhonov regularization to stabilize near-collinear designs

# Factor ETF proxies (tradable; used as fallback when Ken French data is unreachable)
FACTOR_PROXIES = {
    "MKT": "SPY",          # Market
    "SMB": "IWM",          # Small minus Big (approx via Russell 2000)
    "HML": "VTV",          # Value (Vanguard Value ETF)
    "QMJ": "QUAL",         # Quality
    "MOM": "MTUM",         # Momentum
}


def _fetch_kf_csv(url: str, cache_name: str) -> pd.DataFrame | None:
    """Download and parse a Ken French factor-data CSV (zipped). 24h cached."""
    _KF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _KF_CACHE_DIR / f"{cache_name}.csv"
    now = datetime.now(timezone.utc)

    # Serve from cache if fresh
    if cache_path.exists():
        age_hours = (now - datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc)).total_seconds() / 3600
        if age_hours < _KF_CACHE_TTL_HOURS:
            try:
                return pd.read_csv(cache_path, index_col=0, parse_dates=True)
            except Exception:
                pass

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "robin-research/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            zbytes = resp.read()
        with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
            names = z.namelist()
            if not names:
                return None
            with z.open(names[0]) as f:
                text = f.read().decode("latin-1", errors="replace")
        # Ken French CSVs have a header preamble; find the first YYYYMMDD line
        lines = text.splitlines()
        data_start = None
        for i, line in enumerate(lines):
            parts = line.split(",")
            if parts and parts[0].strip().isdigit() and len(parts[0].strip()) == 8:
                data_start = i
                break
        if data_start is None:
            return None
        # Header is the line just before data_start
        header_line = lines[data_start - 1] if data_start > 0 else ""
        header_cols = [c.strip() for c in header_line.split(",")]
        if not header_cols or not header_cols[0]:
            header_cols[0] = "Date"
        # Take contiguous numeric rows
        data_rows = []
        for ln in lines[data_start:]:
            parts = [p.strip() for p in ln.split(",")]
            if not parts or not parts[0].isdigit() or len(parts[0]) != 8:
                break
            data_rows.append(parts)
        if not data_rows:
            return None
        df = pd.DataFrame(data_rows, columns=header_cols)
        df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d")
        df = df.set_index("Date")
        # Convert to float / percent
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce") / 100.0
        df = df.dropna(how="all")
        df.to_csv(cache_path)
        return df
    except Exception:
        return None


def _load_ken_french_factors(period: str) -> pd.DataFrame | None:
    """Return a DataFrame with columns [Mkt-RF, SMB, HML, RMW, CMA, MOM, RF] when available."""
    ff5 = _fetch_kf_csv(_KF_FF5_URL, "ff5_daily")
    mom = _fetch_kf_csv(_KF_MOM_URL, "mom_daily")
    if ff5 is None:
        return None
    out = ff5.copy()
    if mom is not None and "Mom   " in mom.columns:  # Ken French column is literally "Mom   "
        out["MOM"] = mom["Mom   "].reindex(out.index)
    elif mom is not None:
        # Find the momentum column regardless of trailing-space quirks
        mom_col = next((c for c in mom.columns if c.strip().lower().startswith("mom")), None)
        if mom_col:
            out["MOM"] = mom[mom_col].reindex(out.index)

    # Date-range filter: period maps to lookback days
    period_days = {"1mo": 22, "3mo": 63, "6mo": 126, "1y": 252, "2y": 504, "5y": 1260}.get(period, 252)
    cutoff = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=int(period_days * 1.5))
    return out.loc[out.index >= cutoff].dropna(how="all")


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


def _regress_ridge(y: np.ndarray, X: np.ndarray, ridge_lambda: float = _RIDGE_LAMBDA) -> tuple[np.ndarray, float, float]:
    """
    Ridge-regularized OLS: β = (X'X + λI)⁻¹ X'y. Stabilizes when factor proxies
    are collinear. Returns (betas, r_squared, condition_number).
    """
    try:
        k = X.shape[1]
        I = np.eye(k)
        # Don't regularize the intercept (first column)
        I[0, 0] = 0.0
        xtx = X.T @ X + ridge_lambda * I
        xty = X.T @ y
        betas = np.linalg.solve(xtx, xty)
        y_hat = X @ betas
        ss_res = float(np.sum((y - y_hat) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        cond = float(np.linalg.cond(X))
        return betas, r2, cond
    except Exception:
        return np.array([]), 0.0, float("inf")


# Backward compatibility
def _regress_ols(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, float]:
    betas, r2, _ = _regress_ridge(y, X, ridge_lambda=0.0)
    return betas, r2


def compute_factor_attribution(symbol: str, period: str = "1y") -> dict:
    """
    Regress a symbol's excess returns against Fama-French 5+MOM factors.
    Prefers Ken French's published daily series (canonical). Falls back to
    tradable ETF proxies with ridge regularization when Ken French data is
    unreachable.
    """
    sym = symbol.upper()

    # Try Ken French canonical data first
    kf = _load_ken_french_factors(period)
    if kf is not None and len(kf) > 60:
        sym_returns = _download_returns([sym], period=period)
        if not sym_returns.empty and sym in sym_returns.columns:
            # Align dates
            sym_series = sym_returns[sym].copy()
            sym_series.index = pd.to_datetime(sym_series.index).tz_localize(None)
            kf_idx_aligned = kf.index.tz_localize(None) if kf.index.tz is not None else kf.index
            kf_aligned = kf.copy()
            kf_aligned.index = kf_idx_aligned

            joined = pd.concat([sym_series.rename("sym"), kf_aligned], axis=1, join="inner").dropna()
            if len(joined) >= 60:
                rf_col = next((c for c in joined.columns if c.strip().upper() == "RF"), None)
                rf = joined[rf_col].values if rf_col else 0.0
                y = joined["sym"].values - rf
                factor_cols = [c for c in ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "MOM"] if c in joined.columns]
                if len(factor_cols) >= 3:
                    X_factors = joined[factor_cols].values
                    X = np.column_stack([np.ones(len(y)), X_factors])
                    betas, r2, cond = _regress_ridge(y, X)
                    if len(betas) > 0:
                        alpha_daily = float(betas[0])
                        return {
                            "available": True,
                            "symbol": sym,
                            "source": "ken_french_canonical",
                            "period": period,
                            "samples": len(joined),
                            "alpha_daily": round(alpha_daily, 6),
                            "alpha_annual_pct": round(alpha_daily * 252 * 100, 3),
                            "factor_betas": {n: round(float(b), 3) for n, b in zip(factor_cols, betas[1:])},
                            "r_squared": round(r2, 3),
                            "factors_used": factor_cols,
                            "condition_number": round(cond, 1),
                            "ridge_lambda": _RIDGE_LAMBDA,
                        }

    # Fallback: ETF proxies (explicit warning about collinearity)
    factor_symbols = list(FACTOR_PROXIES.values())
    all_symbols = [sym] + factor_symbols
    returns = _download_returns(all_symbols, period=period)
    if returns.empty or sym not in returns.columns:
        return {"available": False, "reason": "insufficient_data"}
    returns = returns.dropna()
    if len(returns) < 60:
        return {"available": False, "reason": "insufficient_history"}

    y = returns[sym].values
    X_cols: list[np.ndarray] = []
    factor_names: list[str] = []
    for name, proxy in FACTOR_PROXIES.items():
        if proxy not in returns.columns:
            continue
        if name == "SMB" and "SPY" in returns.columns:
            X_cols.append((returns[proxy] - returns["SPY"]).values)
            factor_names.append(name)
        elif name == "HML":
            X_cols.append(
                (returns[proxy] - returns["SPY"]).values if "SPY" in returns.columns else returns[proxy].values
            )
            factor_names.append(name)
        elif name == "MKT":
            X_cols.append(returns[proxy].values)
            factor_names.append(name)
        else:
            X_cols.append(returns[proxy].values)
            factor_names.append(name)

    if not X_cols:
        return {"available": False, "reason": "no_factor_proxies_available"}

    X = np.column_stack([np.ones(len(y))] + X_cols)
    betas, r2, cond = _regress_ridge(y, X)
    if len(betas) == 0:
        return {"available": False, "reason": "regression_failed"}

    alpha_daily = float(betas[0])
    stability_warning = None
    if cond > 1e4:
        stability_warning = f"proxy_collinearity_high_cond={cond:.0f}; consider Ken French"

    return {
        "available": True,
        "symbol": sym,
        "source": "etf_proxies_ridge",
        "period": period,
        "samples": len(returns),
        "alpha_daily": round(alpha_daily, 6),
        "alpha_annual_pct": round(alpha_daily * 252 * 100, 3),
        "factor_betas": {n: round(float(b), 3) for n, b in zip(factor_names, betas[1:])},
        "r_squared": round(r2, 3),
        "factors_used": factor_names,
        "condition_number": round(cond, 1),
        "ridge_lambda": _RIDGE_LAMBDA,
        "stability_warning": stability_warning,
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
