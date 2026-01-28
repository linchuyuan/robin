"""Portfolio helpers for Robinhood CLI."""

from __future__ import annotations

import robin_stocks.robinhood as rh


def list_positions() -> list[dict[str, str]]:
    positions = rh.get_open_stock_positions()
    return [dict(pos) for pos in positions if float(pos.get("quantity", "0")) > 0]


def get_quote(symbol: str) -> dict[str, str]:
    return rh.get_latest_price(symbol)
