"""Quantitative analysis helpers for MCP tools."""
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf
import math

def calculate_rsi(series, period=14):
    """Calculate Relative Strength Index (RSI) using Wilder's Smoothing."""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)

    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_atr(high, low, close, period=14):
    """Calculate Average True Range (ATR)."""
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def calculate_relative_strength(series, benchmark_series, period=252):
    """
    Calculate Relative Strength (RS) ratio and its percentile rank.
    RS = Stock / Benchmark
    Returns the percentile (0-100) of the current RS value over the lookback period.
    """
    # Align and sanitize series
    common_index = series.index.intersection(benchmark_series.index)
    if len(common_index) < period:
        return None

    stock = pd.to_numeric(series.loc[common_index], errors="coerce")
    bench = pd.to_numeric(benchmark_series.loc[common_index], errors="coerce")
    valid = bench > 0
    stock = stock[valid]
    bench = bench[valid]
    if len(stock) < period:
        return None

    rs_ratio = (stock / bench).replace([float("inf"), float("-inf")], pd.NA).dropna()
    if len(rs_ratio) < period:
        return None
    # Calculate percentile rank of current value within the lookback window
    # We want to know: is the RS ratio high relative to its recent history?
    current_rs = rs_ratio.iloc[-1]
    history_rs = rs_ratio.iloc[-period:]
    percentile = (history_rs <= current_rs).mean() * 100
    return percentile

def _norm_cdf(x):
    """Cumulative distribution function for the standard normal distribution."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def _norm_pdf(x):
    """Probability density function for the standard normal distribution."""
    return math.exp(-0.5 * x ** 2) / math.sqrt(2.0 * math.pi)

def calculate_greeks(S, K, T, r, sigma, q=0.0, option_type="call"):
    """
    Calculate Black-Scholes Greeks.
    
    :param S: Underlying price
    :param K: Strike price
    :param T: Time to expiration (in years)
    :param r: Risk-free interest rate (decimal, e.g., 0.05)
    :param sigma: Implied volatility (decimal, e.g., 0.20)
    :param q: Dividend yield (decimal, e.g., 0.01)
    :param option_type: "call" or "put"
    :return: Dictionary with delta, gamma, theta, vega, rho
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return {k: None for k in ["delta", "gamma", "theta", "vega", "rho"]}

    try:
        d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        cdf_d1 = _norm_cdf(d1)
        pdf_d1 = _norm_pdf(d1)
        cdf_d2 = _norm_cdf(d2)
        
        # Common Gamma/Vega (same for calls and puts)
        gamma = (pdf_d1 * math.exp(-q * T)) / (S * sigma * math.sqrt(T))
        vega = S * math.exp(-q * T) * pdf_d1 * math.sqrt(T) / 100.0  # Scaled to 1% change

        if option_type.lower() == "call":
            delta = math.exp(-q * T) * cdf_d1
            theta = ((-S * sigma * math.exp(-q * T) * pdf_d1) / (2 * math.sqrt(T)) 
                     - r * K * math.exp(-r * T) * cdf_d2 
                     + q * S * math.exp(-q * T) * cdf_d1) / 365.0
            rho = (K * T * math.exp(-r * T) * cdf_d2) / 100.0
        else:
            delta = math.exp(-q * T) * (cdf_d1 - 1)
            cdf_neg_d2 = _norm_cdf(-d2)
            cdf_neg_d1 = _norm_cdf(-d1)
            theta = ((-S * sigma * math.exp(-q * T) * pdf_d1) / (2 * math.sqrt(T)) 
                     + r * K * math.exp(-r * T) * cdf_neg_d2 
                     - q * S * math.exp(-q * T) * cdf_neg_d1) / 365.0
            rho = (-K * T * math.exp(-r * T) * cdf_neg_d2) / 100.0

        return {
            "delta": round(delta, 4),
            "gamma": round(gamma, 4),
            "theta": round(theta, 4),
            "vega": round(vega, 4),
            "rho": round(rho, 4)
        }
    except Exception:
        return {k: None for k in ["delta", "gamma", "theta", "vega", "rho"]}

def calculate_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """Calculate MACD, Signal line, and Histogram."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def calculate_bollinger_bands(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> dict:
    """Calculate Bollinger Bands (upper, middle, lower) and %B."""
    middle = close.rolling(window=period).mean()
    rolling_std = close.rolling(window=period).std()
    upper = middle + std_dev * rolling_std
    lower = middle - std_dev * rolling_std
    pct_b = (close - lower) / (upper - lower)
    bandwidth = (upper - lower) / middle
    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "pct_b": pct_b,
        "bandwidth": bandwidth,
    }


def calculate_iv_rank(symbol: str, current_iv: float | None = None) -> dict | None:
    """
    Calculate IV Rank and IV Percentile for a symbol.
    IV Rank = (current_iv - 52w_low_iv) / (52w_high_iv - 52w_low_iv) * 100
    IV Percentile = % of days in past year where IV was below current IV
    Uses realized volatility as proxy when current IV is not provided.
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1y")
        if len(hist) < 30:
            return None

        daily_returns = hist["Close"].pct_change().dropna()
        rolling_iv = daily_returns.rolling(window=20).std() * math.sqrt(252)
        rolling_iv = rolling_iv.dropna()
        if len(rolling_iv) < 20:
            return None

        if current_iv is not None and current_iv > 0:
            iv_now = current_iv
        else:
            iv_now = float(rolling_iv.iloc[-1])

        iv_high = float(rolling_iv.max())
        iv_low = float(rolling_iv.min())
        iv_range = iv_high - iv_low

        iv_rank = ((iv_now - iv_low) / iv_range * 100.0) if iv_range > 0 else 50.0
        iv_percentile = float((rolling_iv <= iv_now).mean() * 100.0)

        return {
            "iv_current": round(iv_now, 4),
            "iv_52w_high": round(iv_high, 4),
            "iv_52w_low": round(iv_low, 4),
            "iv_rank": round(iv_rank, 2),
            "iv_percentile": round(iv_percentile, 2),
        }
    except Exception:
        return None


def detect_unusual_options_activity(calls: list[dict], puts: list[dict], current_price: float) -> dict:
    """
    Analyze option chain data for unusual activity signals.
    Detects: high volume/OI ratios, volume spikes, skew anomalies.
    """
    unusual_calls = []
    unusual_puts = []
    total_call_premium = 0.0
    total_put_premium = 0.0

    def _analyze_side(options: list[dict], side: str) -> list[dict]:
        nonlocal total_call_premium, total_put_premium
        unusual = []
        for opt in options:
            vol = int(opt.get("volume") or 0)
            oi = int(opt.get("open_interest") or 0)
            strike = float(opt.get("strike") or 0)
            mid = float(opt.get("price") or opt.get("mid") or 0)
            iv = float(opt.get("implied_volatility") or 0)

            premium_traded = vol * mid * 100
            if side == "call":
                total_call_premium += premium_traded
            else:
                total_put_premium += premium_traded

            vol_oi_ratio = (vol / oi) if oi > 0 else 0
            if vol >= 500 and vol_oi_ratio > 2.0:
                unusual.append({
                    "strike": strike,
                    "volume": vol,
                    "open_interest": oi,
                    "vol_oi_ratio": round(vol_oi_ratio, 2),
                    "implied_volatility": round(iv, 4),
                    "premium_traded": round(premium_traded, 2),
                    "moneyness": round((strike / current_price - 1) * 100, 2) if current_price > 0 else None,
                    "side": side,
                })
        return unusual

    unusual_calls = _analyze_side(calls, "call")
    unusual_puts = _analyze_side(puts, "put")

    all_unusual = sorted(
        unusual_calls + unusual_puts,
        key=lambda x: x.get("premium_traded", 0),
        reverse=True,
    )[:10]

    premium_ratio = None
    if total_call_premium > 0:
        premium_ratio = round(total_put_premium / total_call_premium, 4)

    net_premium_bias = "neutral"
    if premium_ratio is not None:
        if premium_ratio > 1.5:
            net_premium_bias = "bearish"
        elif premium_ratio < 0.6:
            net_premium_bias = "bullish"

    return {
        "unusual_activity": all_unusual,
        "unusual_call_count": len(unusual_calls),
        "unusual_put_count": len(unusual_puts),
        "total_call_premium_traded": round(total_call_premium, 2),
        "total_put_premium_traded": round(total_put_premium, 2),
        "put_call_premium_ratio": premium_ratio,
        "net_premium_bias": net_premium_bias,
    }


def get_portfolio_risk_summary(positions: list[dict]) -> dict:
    """
    Calculate portfolio-level risk metrics from current positions.
    Includes: total exposure, beta-weighted delta, concentration, sector breakdown.
    """
    if not positions:
        return {"error": "No positions provided."}

    total_equity = sum(float(p.get("equity") or 0) for p in positions)
    if total_equity <= 0:
        return {"error": "Total equity is zero or negative."}

    symbols = [p["symbol"] for p in positions if p.get("symbol")]
    if not symbols:
        return {"error": "No valid symbols in positions."}

    sector_exposure: dict[str, float] = {}
    position_weights: list[dict] = []
    total_unrealized_pnl = 0.0
    total_day_pnl = 0.0

    for pos in positions:
        sym = pos.get("symbol", "")
        equity = float(pos.get("equity") or 0)
        weight = (equity / total_equity * 100) if total_equity > 0 else 0
        unrealized = float(pos.get("equity_change") or 0)
        day_pnl = float(pos.get("intraday_profit_loss") or 0)

        total_unrealized_pnl += unrealized
        total_day_pnl += day_pnl

        position_weights.append({
            "symbol": sym,
            "equity": round(equity, 2),
            "weight_pct": round(weight, 2),
            "unrealized_pnl": round(unrealized, 2),
            "day_pnl": round(day_pnl, 2),
        })

        sector = str(pos.get("sector") or "Unknown")
        sector_exposure[sector] = sector_exposure.get(sector, 0.0) + equity

    position_weights.sort(key=lambda x: x.get("weight_pct", 0), reverse=True)
    sector_breakdown = [
        {"sector": s, "equity": round(e, 2), "weight_pct": round(e / total_equity * 100, 2)}
        for s, e in sorted(sector_exposure.items(), key=lambda x: x[1], reverse=True)
    ]

    top_weight = position_weights[0]["weight_pct"] if position_weights else 0
    hhi = sum((w["weight_pct"] / 100) ** 2 for w in position_weights)

    concentration_risk = "low"
    if top_weight > 30 or hhi > 0.25:
        concentration_risk = "high"
    elif top_weight > 20 or hhi > 0.18:
        concentration_risk = "medium"

    return {
        "total_equity": round(total_equity, 2),
        "position_count": len(positions),
        "total_unrealized_pnl": round(total_unrealized_pnl, 2),
        "total_day_pnl": round(total_day_pnl, 2),
        "positions": position_weights,
        "sector_breakdown": sector_breakdown,
        "concentration": {
            "hhi": round(hhi, 4),
            "top_position_weight_pct": round(top_weight, 2),
            "risk_level": concentration_risk,
        },
    }


def get_technical_indicators(symbol: str) -> dict:
    """
    Calculate technical indicators for a given symbol.
    Returns a dictionary with calculated metrics.
    """
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2y")

        spy_ticker = yf.Ticker("SPY")
        spy_hist = spy_ticker.history(period="2y")
        
        if len(hist) < 200:
             return {"error": f"Not enough history for {symbol} (found {len(hist)} days)"}

        current_price = hist['Close'].iloc[-1]
        
        # SMAs
        sma_20 = hist['Close'].rolling(window=20).mean().iloc[-1]
        sma_50 = hist['Close'].rolling(window=50).mean().iloc[-1]
        sma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]

        # EMAs
        ema_9 = hist['Close'].ewm(span=9, adjust=False).mean().iloc[-1]
        ema_21 = hist['Close'].ewm(span=21, adjust=False).mean().iloc[-1]

        # RSI
        rsi_series = calculate_rsi(hist['Close'])
        rsi_14 = rsi_series.iloc[-1]
        
        # ATR
        atr_series = calculate_atr(hist['High'], hist['Low'], hist['Close'])
        atr_14 = atr_series.iloc[-1]

        # MACD
        macd_data = calculate_macd(hist['Close'])
        macd_val = macd_data["macd"].iloc[-1]
        macd_signal = macd_data["signal"].iloc[-1]
        macd_hist = macd_data["histogram"].iloc[-1]
        macd_prev_hist = macd_data["histogram"].iloc[-2] if len(macd_data["histogram"]) >= 2 else 0
        macd_crossover = "bullish" if macd_hist > 0 and macd_prev_hist <= 0 else (
            "bearish" if macd_hist < 0 and macd_prev_hist >= 0 else "none"
        )

        # Bollinger Bands
        bb = calculate_bollinger_bands(hist['Close'])
        bb_upper = bb["upper"].iloc[-1]
        bb_lower = bb["lower"].iloc[-1]
        bb_pct_b = bb["pct_b"].iloc[-1]
        bb_bandwidth = bb["bandwidth"].iloc[-1]

        # Relative Strength vs SPY
        rs_percentile = calculate_relative_strength(hist['Close'], spy_hist['Close'], period=252)
        
        # Returns
        ret_5d = (hist['Close'].iloc[-1] / hist['Close'].iloc[-6] - 1) if len(hist) >= 6 else 0.0
        ret_20d = (hist['Close'].iloc[-1] / hist['Close'].iloc[-21] - 1) if len(hist) >= 21 else 0.0
        
        # Relative Volume
        vol_20d_avg = hist['Volume'].iloc[-21:-1].mean()
        curr_vol = hist['Volume'].iloc[-1]
        rel_vol = (curr_vol / vol_20d_avg) if vol_20d_avg > 0 else 1.0

        # VWAP (intraday proxy using daily typical price * volume)
        typical_price = (hist['High'] + hist['Low'] + hist['Close']) / 3
        cumulative_vwap = (typical_price * hist['Volume']).rolling(window=20).sum() / hist['Volume'].rolling(window=20).sum()
        vwap_20d = cumulative_vwap.iloc[-1] if not pd.isna(cumulative_vwap.iloc[-1]) else None

        # IV Rank
        iv_data = calculate_iv_rank(symbol)

        # ATR-based Sizing
        risk_unit = 1000.0
        stop_distance = 2.0 * atr_14 if atr_14 and atr_14 > 0 else None
        vol_shares = int(risk_unit / stop_distance) if stop_distance else 0

        # Trend strength composite
        above_sma_50 = float(current_price) > float(sma_50) if not pd.isna(sma_50) else None
        above_sma_200 = float(current_price) > float(sma_200) if not pd.isna(sma_200) else None
        golden_cross = float(sma_50) > float(sma_200) if not (pd.isna(sma_50) or pd.isna(sma_200)) else None

        trend_score = 0
        if above_sma_50:
            trend_score += 1
        if above_sma_200:
            trend_score += 1
        if golden_cross:
            trend_score += 1
        if not pd.isna(macd_hist) and macd_hist > 0:
            trend_score += 1
        if not pd.isna(rsi_14) and 40 < float(rsi_14) < 70:
            trend_score += 1
        trend_label = "strong_up" if trend_score >= 4 else ("up" if trend_score >= 3 else ("neutral" if trend_score >= 2 else "down"))

        result = {
            "symbol": symbol.upper(),
            "price": round(float(current_price), 2),
            "sma_20": round(float(sma_20), 2) if not pd.isna(sma_20) else None,
            "sma_50": round(float(sma_50), 2) if not pd.isna(sma_50) else None,
            "sma_200": round(float(sma_200), 2) if not pd.isna(sma_200) else None,
            "ema_9": round(float(ema_9), 2) if not pd.isna(ema_9) else None,
            "ema_21": round(float(ema_21), 2) if not pd.isna(ema_21) else None,
            "rsi_14": round(float(rsi_14), 2) if not pd.isna(rsi_14) else None,
            "atr_14": round(float(atr_14), 2) if not pd.isna(atr_14) else None,
            "macd": {
                "value": round(float(macd_val), 4) if not pd.isna(macd_val) else None,
                "signal": round(float(macd_signal), 4) if not pd.isna(macd_signal) else None,
                "histogram": round(float(macd_hist), 4) if not pd.isna(macd_hist) else None,
                "crossover": macd_crossover,
            },
            "bollinger": {
                "upper": round(float(bb_upper), 2) if not pd.isna(bb_upper) else None,
                "lower": round(float(bb_lower), 2) if not pd.isna(bb_lower) else None,
                "pct_b": round(float(bb_pct_b), 4) if not pd.isna(bb_pct_b) else None,
                "bandwidth": round(float(bb_bandwidth), 4) if not pd.isna(bb_bandwidth) else None,
            },
            "vwap_20d": round(float(vwap_20d), 2) if vwap_20d is not None else None,
            "rs_spy_percentile": round(float(rs_percentile), 2) if rs_percentile is not None else None,
            "return_5d": round(float(ret_5d), 4),
            "return_20d": round(float(ret_20d), 4),
            "relative_volume": round(float(rel_vol), 2),
            "daily_relative_volume": round(float(rel_vol), 2),
            "relative_volume_context": {
                "method": "latest_daily_volume_vs_prior_20_full_day_average",
                "current_volume": int(curr_vol) if not pd.isna(curr_vol) else None,
                "prior_20d_avg_volume": round(float(vol_20d_avg), 2) if not pd.isna(vol_20d_avg) else None,
                "valid_for": "daily_or_near_close",
                "intraday_low_signal_reliable": False,
                "decision_role": "soft_context_only_during_market_hours",
            },
            "trend": {
                "score": trend_score,
                "label": trend_label,
                "above_sma_50": above_sma_50,
                "above_sma_200": above_sma_200,
                "golden_cross": golden_cross,
            },
            "volatility_sizing": {
                "risk_unit": risk_unit,
                "atr_stop_dist": round(float(stop_distance), 2) if stop_distance else None,
                "suggested_shares_per_1k_risk": vol_shares,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timezone": "UTC",
        }

        if iv_data:
            result["iv_rank_data"] = iv_data

        return result
    except Exception as e:
        return {"error": str(e)}


def get_volume_velocity(
    symbol: str,
    interval: str = "5m",
    period: str = "5d",
    baseline_bars: int = 48,
    series_points: int = 24,
) -> dict:
    """
    Calculate intraday volume velocity as a time series.

    This is intended for intraday participation checks. It compares each intraday
    bar's volume against a time-of-day normalized baseline built from the same bar
    slot across prior sessions. If there are not enough same-slot observations, it
    falls back to a rolling prior-N-bar baseline.
    """
    try:
        sym = str(symbol).upper().strip()
        allowed_intervals = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}
        if interval not in allowed_intervals:
            return {
                "symbol": sym,
                "error": f"Unsupported interval '{interval}'. Use one of: {', '.join(sorted(allowed_intervals))}",
            }

        baseline = max(2, int(baseline_bars or 48))
        points = max(1, min(int(series_points or 24), 200))

        ticker = yf.Ticker(sym)
        hist = ticker.history(period=period, interval=interval, prepost=False)
        if hist is None or hist.empty:
            return {"symbol": sym, "error": f"No intraday history returned for {sym}."}
        if "Volume" not in hist.columns:
            return {"symbol": sym, "error": "Intraday history is missing Volume."}

        volume = pd.to_numeric(hist["Volume"], errors="coerce").fillna(0)
        usable = pd.DataFrame({"volume": volume}, index=hist.index)
        usable = usable[usable["volume"] >= 0].copy()
        if len(usable) < baseline + 2:
            return {
                "symbol": sym,
                "interval": interval,
                "period": period,
                "error": f"Not enough intraday bars for baseline_bars={baseline} (found {len(usable)}).",
            }

        index_series = usable.index.to_series()
        try:
            local_index = index_series.dt.tz_convert("America/New_York")
        except Exception:
            local_index = index_series
        usable["trade_date"] = local_index.dt.strftime("%Y-%m-%d")
        usable["time_slot"] = local_index.dt.strftime("%H:%M")
        usable["slot_obs_count"] = usable.groupby("time_slot").cumcount()

        same_slot_avg = []
        same_slot_std = []
        same_slot_count = []
        for i, row in usable.iterrows():
            prior_same_slot = usable.loc[
                (usable.index < i) & (usable["time_slot"] == row["time_slot"]), "volume"
            ].tail(baseline)
            same_slot_count.append(int(len(prior_same_slot)))
            if len(prior_same_slot) >= 2:
                same_slot_avg.append(float(prior_same_slot.mean()))
                same_slot_std.append(float(prior_same_slot.std(ddof=1)))
            else:
                same_slot_avg.append(None)
                same_slot_std.append(None)

        usable["baseline_avg_volume_same_slot"] = same_slot_avg
        usable["baseline_std_volume_same_slot"] = same_slot_std
        usable["same_slot_sample_size"] = same_slot_count

        usable["baseline_avg_volume_rolling"] = usable["volume"].rolling(window=baseline).mean().shift(1)
        usable["baseline_std_volume_rolling"] = usable["volume"].rolling(window=baseline).std().shift(1)

        usable["baseline_type"] = usable["same_slot_sample_size"].apply(
            lambda n: "same_time_of_day" if n >= 2 else "rolling_prior_bars"
        )
        usable["baseline_avg_volume"] = usable.apply(
            lambda row: row["baseline_avg_volume_same_slot"]
            if row["baseline_type"] == "same_time_of_day"
            else row["baseline_avg_volume_rolling"],
            axis=1,
        )
        usable["baseline_std_volume"] = usable.apply(
            lambda row: row["baseline_std_volume_same_slot"]
            if row["baseline_type"] == "same_time_of_day"
            else row["baseline_std_volume_rolling"],
            axis=1,
        )

        usable["velocity_ratio"] = usable.apply(
            lambda row: (row["volume"] / row["baseline_avg_volume"])
            if pd.notna(row["baseline_avg_volume"]) and row["baseline_avg_volume"] > 0
            else None,
            axis=1,
        )
        usable["velocity_z_score"] = usable.apply(
            lambda row: ((row["volume"] - row["baseline_avg_volume"]) / row["baseline_std_volume"])
            if pd.notna(row["baseline_std_volume"]) and row["baseline_std_volume"] > 0
            else None,
            axis=1,
        )
        usable["volume_change"] = usable["volume"].diff()
        usable["volume_change_pct"] = usable["volume"].pct_change().replace([float("inf"), float("-inf")], pd.NA)

        valid = usable.dropna(subset=["baseline_avg_volume", "velocity_ratio"]).copy()
        if valid.empty:
            return {
                "symbol": sym,
                "interval": interval,
                "period": period,
                "error": "Unable to calculate volume velocity from returned intraday bars.",
            }

        latest = valid.iloc[-1]
        previous = valid.iloc[-2] if len(valid) >= 2 else None
        recent = valid.tail(min(6, len(valid)))
        if len(recent) >= 2:
            ratio_delta = float(recent["velocity_ratio"].iloc[-1] - recent["velocity_ratio"].iloc[0])
            trend = "rising" if ratio_delta > 0.15 else ("falling" if ratio_delta < -0.15 else "flat")
        else:
            ratio_delta = 0.0
            trend = "flat"

        def _round_optional(value, digits=4):
            if value is None or pd.isna(value):
                return None
            return round(float(value), digits)

        series = []
        for ts, row in valid.tail(points).iterrows():
            series.append(
                {
                    "timestamp": ts.isoformat(),
                    "volume": int(row["volume"]),
                    "baseline_avg_volume": _round_optional(row["baseline_avg_volume"], 2),
                    "baseline_type": row.get("baseline_type"),
                    "same_slot_sample_size": int(row["same_slot_sample_size"]) if pd.notna(row.get("same_slot_sample_size")) else None,
                    "velocity_ratio": _round_optional(row["velocity_ratio"], 4),
                    "velocity_z_score": _round_optional(row["velocity_z_score"], 4),
                    "volume_change": int(row["volume_change"]) if not pd.isna(row["volume_change"]) else None,
                    "volume_change_pct": _round_optional(row["volume_change_pct"], 4),
                }
            )

        latest_ratio = _round_optional(latest["velocity_ratio"], 4)
        if latest_ratio is None:
            classification = "unknown"
        elif latest_ratio >= 2.5:
            classification = "strong_spike"
        elif latest_ratio >= 1.8:
            classification = "unusual_acceleration"
        elif latest_ratio >= 1.2:
            classification = "active"
        elif latest_ratio >= 0.8:
            classification = "normal"
        else:
            classification = "below_recent_pace"

        baseline_method = "same_time_of_day_prior_sessions" if latest.get("baseline_type") == "same_time_of_day" else "rolling_prior_N_bar_fallback"

        return {
            "symbol": sym,
            "interval": interval,
            "period": period,
            "baseline_bars": baseline,
            "series_points": len(series),
            "latest": {
                "timestamp": valid.index[-1].isoformat(),
                "volume": int(latest["volume"]),
                "previous_volume": int(previous["volume"]) if previous is not None else None,
                "baseline_avg_volume": _round_optional(latest["baseline_avg_volume"], 2),
                "baseline_type": latest.get("baseline_type"),
                "same_slot_sample_size": int(latest["same_slot_sample_size"]) if pd.notna(latest.get("same_slot_sample_size")) else None,
                "velocity_ratio": latest_ratio,
                "velocity_z_score": _round_optional(latest["velocity_z_score"], 4),
                "volume_change": int(latest["volume_change"]) if not pd.isna(latest["volume_change"]) else None,
                "volume_change_pct": _round_optional(latest["volume_change_pct"], 4),
                "classification": classification,
            },
            "trend": {
                "label": trend,
                "ratio_delta_recent": round(ratio_delta, 4),
            },
            "series": series,
            "data_quality": {
                "source": "yfinance_intraday_history",
                "method": baseline_method,
                "decision_role": "intraday_participation_confirmation",
                "hard_gate": False,
                "note": "Primary baseline is same time-of-day across prior sessions, with rolling prior-bar fallback when sample size is insufficient. Still limited by Yahoo/yfinance data quality.",
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timezone": "UTC",
        }
    except Exception as e:
        return {"symbol": str(symbol).upper(), "error": str(e)}

def get_sector_performance() -> list:
    """
    Calculate 5-day performance for major sector ETFs.
    """
    sectors = {
        "XLK": "Technology",
        "XLF": "Financial Services",
        "XLE": "Energy",
        "XLV": "Healthcare",
        "XLI": "Industrials",
        "XLC": "Communication Services",
        "XLY": "Consumer Cyclical",
        "XLP": "Consumer Defensive",
        "XLU": "Utilities",
        "XLRE": "Real Estate",
    }
    
    results = []
    try:
        tickers_list = list(sectors.keys())
        # Batch download
        data = yf.download(tickers_list, period="5d", progress=False, auto_adjust=False)
        
        # Handle MultiIndex columns (Price, Ticker) if present
        # yfinance > 0.2 returns columns like ('Close', 'XLK')
        # We want 'Close'
        
        close_data = data['Close'] if 'Close' in data else data
        
        for symbol, name in sectors.items():
            try:
                # Extract series for this symbol
                if isinstance(close_data.columns, pd.MultiIndex):
                     # If multi-index, check if symbol is in second level
                     if symbol in close_data.columns.get_level_values(1):
                         series = close_data.xs(symbol, axis=1, level=1)
                     elif symbol in close_data.columns:
                         series = close_data[symbol]
                     else:
                         continue
                else:
                     if symbol in close_data.columns:
                         series = close_data[symbol]
                     else:
                         continue

                series = series.dropna()
                if len(series) >= 2:
                    start_price = series.iloc[0]
                    end_price = series.iloc[-1]
                    pct_change = (end_price - start_price) / start_price
                    results.append({
                        "symbol": symbol,
                        "name": name,
                        "return_5d": round(float(pct_change), 4)
                    })
            except Exception:
                continue
        
        # Sort by return descending
        results.sort(key=lambda x: x['return_5d'], reverse=True)
        return results
        
    except Exception as e:
        return [{"error": str(e)}]

def get_portfolio_correlation(symbols: list[str], period="1y") -> dict:
    """
    Calculate correlation matrix for a list of symbols.
    Returns a dictionary with the correlation matrix and high-correlation pairs (>0.7).
    """
    if not symbols or len(symbols) < 2:
        return {"error": "Need at least 2 symbols for correlation."}

    # Clean symbols
    raw_symbols = [str(s).upper().strip() for s in symbols if str(s).strip()]
    clean_symbols = list(dict.fromkeys(s for s in raw_symbols if s.isalpha() and 1 <= len(s) <= 5))
    dropped_symbols = [s for s in raw_symbols if s not in clean_symbols]
    if len(clean_symbols) < 2:
        return {"error": "Need at least 2 valid symbols."}

    try:
        # Batch download
        data = yf.download(clean_symbols, period=period, progress=False, auto_adjust=False)
        close_data = data['Close'] if 'Close' in data else data
        if isinstance(close_data, pd.Series):
            return {"error": "Insufficient valid symbols/time series after download."}

        close_data = close_data.apply(pd.to_numeric, errors="coerce").dropna(axis=1, how="all")
        if close_data.shape[1] < 2:
            return {"error": "Insufficient valid symbols/time series after download."}
        effective_symbols = [str(c) for c in close_data.columns]
        dropped_symbols.extend([s for s in clean_symbols if s not in effective_symbols and s not in dropped_symbols])

        corr_matrix = close_data.corr(min_periods=20)
        
        # Identify high correlation pairs (> 0.7)
        high_corr_pairs = []
        # Iterate over upper triangle
        cols = corr_matrix.columns
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                sym1 = cols[i]
                sym2 = cols[j]
                val = corr_matrix.iloc[i, j]
                if pd.notna(val) and val > 0.7:
                    high_corr_pairs.append({
                        "pair": [str(sym1), str(sym2)],
                        "correlation": round(float(val), 2)
                    })
        
        # Convert matrix to dict for JSON
        # { "AAPL": { "MSFT": 0.8, ... }, ... }
        corr_clean = corr_matrix.round(2).where(pd.notna(corr_matrix), None)
        matrix_dict = corr_clean.to_dict()
        
        return {
            "symbols": clean_symbols,
            "effective_symbols": effective_symbols,
            "dropped_symbols": dropped_symbols,
            "correlation_matrix": matrix_dict,
            "high_correlation_pairs": high_corr_pairs,
            "count": len(high_corr_pairs)
        }
    except Exception as e:
        return {"error": str(e)}

def get_peers(symbol: str, limit: int = 6) -> dict:
    """Return peer ticker candidates for a symbol.

    Strategy:
    1) Yahoo search-based peers (best effort)
    2) Sector fallback list if search has no usable peers
    """
    symbol_up = str(symbol).upper().strip()
    try:
        ticker = yf.Ticker(symbol_up)
        info = ticker.info or {}
        sector = info.get("sector")
        industry = info.get("industry")

        if not sector and not industry:
            return {"error": f"Sector/Industry not found for {symbol_up}"}

        peers: list[dict] = []
        seen: set[str] = {symbol_up}

        # Best-effort dynamic peers from Yahoo symbol search.
        try:
            query = f"{symbol_up} {industry or sector or ''}".strip()
            search = yf.Search(query=query, max_results=20, news_count=0)
            quotes = getattr(search, "quotes", []) or []
            for q in quotes:
                candidate = str(q.get("symbol") or "").upper().strip()
                quote_type = str(q.get("quoteType") or "").upper()
                if not candidate or candidate in seen:
                    continue
                if not candidate.isalpha() or len(candidate) > 5:
                    continue
                if quote_type and quote_type not in {"EQUITY", "ETF"}:
                    continue
                peers.append(
                    {
                        "symbol": candidate,
                        "name": q.get("shortname") or q.get("longname") or candidate,
                        "source": "yahoo_search",
                    }
                )
                seen.add(candidate)
                if len(peers) >= limit:
                    break
        except Exception:
            # Continue with fallback without failing the endpoint.
            pass

        # Deterministic fallback by sector for robustness.
        if len(peers) < limit:
            sector_fallback = {
                "Technology": ["MSFT", "AAPL", "ORCL", "ADBE", "CRM", "INTC"],
                "Communication Services": ["GOOGL", "META", "NFLX", "DIS", "TMUS"],
                "Consumer Cyclical": ["AMZN", "TSLA", "HD", "MCD", "NKE"],
                "Healthcare": ["UNH", "LLY", "PFE", "JNJ", "MRK"],
                "Financial Services": ["JPM", "BAC", "GS", "MS", "WFC"],
                "Industrials": ["CAT", "GE", "DE", "HON", "BA"],
                "Energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
                "Consumer Defensive": ["PG", "KO", "PEP", "WMT", "COST"],
                "Utilities": ["NEE", "DUK", "SO", "AEP", "XEL"],
                "Real Estate": ["PLD", "AMT", "CCI", "EQIX", "SPG"],
            }
            for candidate in sector_fallback.get(sector or "", []):
                if candidate in seen:
                    continue
                peers.append(
                    {
                        "symbol": candidate,
                        "name": candidate,
                        "source": "sector_fallback",
                    }
                )
                seen.add(candidate)
                if len(peers) >= limit:
                    break

        result_text = (
            f"{symbol_up} peers ({sector or 'Unknown sector'} / {industry or 'Unknown industry'}): "
            + ", ".join(p["symbol"] for p in peers)
            if peers
            else f"No peers found for {symbol_up}."
        )
        return {
            "symbol": symbol_up,
            "sector": sector,
            "industry": industry,
            "peers": peers,
            "count": len(peers),
            "result_text": result_text,
        }
    except Exception as e:
        return {"error": str(e)}
