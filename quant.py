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

def get_technical_indicators(symbol: str) -> dict:
    """
    Calculate technical indicators for a given symbol.
    Returns a dictionary with calculated metrics.
    """
    try:
        # Fetch enough history for 200D SMA
        ticker = yf.Ticker(symbol)
        # Get 2 years to be safe for 200 SMA + volatility
        hist = ticker.history(period="2y")
        
        # Fetch SPY for Relative Strength
        spy_ticker = yf.Ticker("SPY")
        spy_hist = spy_ticker.history(period="2y")
        
        if len(hist) < 200:
             return {"error": f"Not enough history for {symbol} (found {len(hist)} days)"}

        # Current price (last close)
        current_price = hist['Close'].iloc[-1]
        
        # SMAs
        sma_50 = hist['Close'].rolling(window=50).mean().iloc[-1]
        sma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]
        
        # RSI
        rsi_series = calculate_rsi(hist['Close'])
        rsi_14 = rsi_series.iloc[-1]
        
        # ATR
        atr_series = calculate_atr(hist['High'], hist['Low'], hist['Close'])
        atr_14 = atr_series.iloc[-1]
        
        # Relative Strength vs SPY (1-year lookback percentile)
        rs_percentile = calculate_relative_strength(hist['Close'], spy_hist['Close'], period=252)
        
        # Returns
        ret_5d = (hist['Close'].iloc[-1] / hist['Close'].iloc[-6] - 1) if len(hist) >= 6 else 0.0
        ret_20d = (hist['Close'].iloc[-1] / hist['Close'].iloc[-21] - 1) if len(hist) >= 21 else 0.0
        
        # Relative Volume (current volume vs 20D avg)
        # Use the 20 days prior to the last day for the average to avoid skewing with today's partial volume if live
        vol_20d_avg = hist['Volume'].iloc[-21:-1].mean()
        curr_vol = hist['Volume'].iloc[-1]
        rel_vol = (curr_vol / vol_20d_avg) if vol_20d_avg > 0 else 1.0

        # ATR-based Sizing (Volatility Normalization)
        # Suggested shares for $1,000 risk unit with 2xATR stop
        # Risk = 2 * ATR
        # Shares = $1000 / (2 * ATR)
        risk_unit = 1000.0
        stop_distance = 2.0 * atr_14 if atr_14 and atr_14 > 0 else None
        vol_shares = int(risk_unit / stop_distance) if stop_distance else 0

        return {
            "symbol": symbol.upper(),
            "price": round(float(current_price), 2),
            "sma_50": round(float(sma_50), 2) if not pd.isna(sma_50) else None,
            "sma_200": round(float(sma_200), 2) if not pd.isna(sma_200) else None,
            "rsi_14": round(float(rsi_14), 2) if not pd.isna(rsi_14) else None,
            "atr_14": round(float(atr_14), 2) if not pd.isna(atr_14) else None,
            "rs_spy_percentile": round(float(rs_percentile), 2) if rs_percentile is not None else None,
            "return_5d": round(float(ret_5d), 4),
            "return_20d": round(float(ret_20d), 4),
            "relative_volume": round(float(rel_vol), 2),
            "volatility_sizing": {
                "risk_unit": risk_unit,
                "atr_stop_dist": round(float(stop_distance), 2) if stop_distance else None,
                "suggested_shares_per_1k_risk": vol_shares
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timezone": "UTC",
        }
    except Exception as e:
        return {"error": str(e)}

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
        data = yf.download(tickers_list, period="5d", progress=False)
        
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
    clean_symbols = list(dict.fromkeys(str(s).upper().strip() for s in symbols if str(s).strip()))
    if len(clean_symbols) < 2:
        return {"error": "Need at least 2 valid symbols."}

    try:
        # Batch download
        data = yf.download(clean_symbols, period=period, progress=False)
        close_data = data['Close'] if 'Close' in data else data
        if isinstance(close_data, pd.Series):
            return {"error": "Insufficient valid symbols/time series after download."}

        close_data = close_data.apply(pd.to_numeric, errors="coerce").dropna(axis=1, how="all")
        if close_data.shape[1] < 2:
            return {"error": "Insufficient valid symbols/time series after download."}

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
