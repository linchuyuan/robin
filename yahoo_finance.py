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
    return {
        "symbol": symbol.upper(),
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "open": info.get("open"),
        "high": info.get("dayHigh"),
        "low": info.get("dayLow"),
        "volume": info.get("volume"),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "dividend_yield": info.get("dividendYield"),
        "52_week_high": info.get("fiftyTwoWeekHigh"),
        "52_week_low": info.get("fiftyTwoWeekLow"),
    }

def get_yf_news(symbol: str) -> List[Dict[str, Any]]:
    """
    Fetch recent news for a symbol from Yahoo Finance.
    
    :param symbol: Stock ticker symbol
    :return: List of news dictionaries
    """
    ticker = yf.Ticker(symbol)
    news = ticker.news
    return news if news else []

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
