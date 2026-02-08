"""Yahoo Finance helpers for Robinhood CLI."""
from __future__ import annotations

import yfinance as yf
from typing import Any, Dict, List, Optional
import pandas as pd

def get_yf_quote(symbol: str) -> Dict[str, Any]:
    """
    Fetch the latest quote and info for a symbol from Yahoo Finance.
    
    :param symbol: Stock ticker symbol
    :return: Dictionary containing quote information
    """
    ticker = yf.Ticker(symbol)
    info = ticker.info

    # Compute relative volume
    vol = info.get("volume") or 0
    avg_vol = info.get("averageVolume") or 0
    rel_vol = round(vol / avg_vol, 2) if avg_vol and avg_vol > 0 else None

    # Earnings date (may be a list of timestamps, a single timestamp, or None)
    from datetime import datetime as _dt, timezone as _tz
    raw_earnings = info.get("earningsTimestamp") or info.get("earningsDate")
    earnings_date = None
    if raw_earnings:
        try:
            # Unwrap list/tuple to single value
            val = raw_earnings[0] if isinstance(raw_earnings, (list, tuple)) else raw_earnings
            if isinstance(val, (int, float)):
                # Unix timestamp → human-readable date
                earnings_date = _dt.fromtimestamp(val, tz=_tz.utc).strftime('%Y-%m-%d')
            else:
                # Already a string or datetime-like
                earnings_date = str(val)[:10]  # Keep just YYYY-MM-DD
        except Exception:
            earnings_date = str(raw_earnings)

    return {
        "symbol": symbol.upper(),
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "previous_close": info.get("previousClose"),
        "open": info.get("open"),
        "high": info.get("dayHigh"),
        "low": info.get("dayLow"),
        "bid": info.get("bid"),
        "ask": info.get("ask"),
        "volume": vol,
        "average_volume": avg_vol,
        "relative_volume": rel_vol,
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "dividend_yield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "52_week_high": info.get("fiftyTwoWeekHigh"),
        "52_week_low": info.get("fiftyTwoWeekLow"),
        "50_day_avg": info.get("fiftyDayAverage"),
        "200_day_avg": info.get("twoHundredDayAverage"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "short_ratio": info.get("shortRatio"),
        "earnings_date": earnings_date,
        "profit_margins": info.get("profitMargins"),
        "revenue_growth": info.get("revenueGrowth"),
    }

def get_yf_news(symbol: str) -> List[Dict[str, Any]]:
    """
    Fetch recent news for a symbol from Yahoo Finance.
    
    :param symbol: Stock ticker symbol
    :return: List of news dictionaries
    """
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.news
        return news if news else []
    except Exception:
        return []

def get_yf_options(symbol: str, expiration_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch options chain for a symbol.
    
    :param symbol: Stock ticker symbol
    :param expiration_date: Specific expiration date (YYYY-MM-DD). If None, returns available expirations.
    :return: Dictionary containing expiration dates or option chain data
    """
    ticker = yf.Ticker(symbol)
    expirations = ticker.options
    
    if not expirations:
        return {"expirations": []}
    
    if not expiration_date:
        return {"expirations": list(expirations)}
    
    if expiration_date not in expirations:
        raise ValueError(f"Invalid expiration date. Available: {', '.join(expirations)}")
    
    chain = ticker.option_chain(expiration_date)
    
    # Get current price to help identify ATM options
    try:
        current_price = ticker.info.get("currentPrice") or ticker.info.get("regularMarketPrice") or 0.0
    except:
        current_price = 0.0

    # Convert DataFrames to lists of dicts for JSON serialization
    calls = chain.calls.fillna("").to_dict(orient="records")
    puts = chain.puts.fillna("").to_dict(orient="records")
    
    return {
        "symbol": symbol.upper(),
        "expiration_date": expiration_date,
        "current_price": current_price,
        "calls": calls,
        "puts": puts
    }
