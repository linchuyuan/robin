#!/usr/bin/env python3
"""Market data helpers for Robinhood CLI."""

from __future__ import annotations

import robin_stocks.robinhood as rh
from typing import Any

def get_history(symbol: str, interval: str = "day", span: str = "week") -> list[dict[str, Any]]:
    """
    Fetch historical data for a stock.
    
    :param symbol: Stock ticker symbol
    :param interval: Interval for data points (5minute, 10minute, hour, day, week)
    :param span: Time span for data (day, week, month, 3month, year, 5year)
    """
    return rh.get_stock_historicals(symbol, interval=interval, span=span)

def get_news(symbol: str) -> list[dict[str, Any]]:
    """
    Fetch news for a stock.
    
    :param symbol: Stock ticker symbol
    """
    return rh.get_news(symbol)
