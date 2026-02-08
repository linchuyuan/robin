#!/usr/bin/env python3
"""Order-building helpers."""

from __future__ import annotations

from typing import Any

import robin_stocks.robinhood as rh


class OrderValidationError(ValueError):
    pass


def validate_order(symbol: str, qty: float, side: str, order_type: str, price: float | None, stop_price: float | None = None) -> None:
    if side not in {"buy", "sell"}:
        raise OrderValidationError("--side must be 'buy' or 'sell'.")
    if order_type == "limit" and price is None:
        raise OrderValidationError("Limit orders require --price.")
    if order_type == "stop_loss" and stop_price is None:
        raise OrderValidationError("Stop-loss orders require --stop_price.")
    if order_type == "stop_limit" and (price is None or stop_price is None):
        raise OrderValidationError("Stop-limit orders require both --price and --stop_price.")
    if order_type == "trailing_stop" and stop_price is None:
        raise OrderValidationError("Trailing stop orders require --stop_price (as trail amount in $).")
    if qty <= 0:
        raise OrderValidationError("Quantity must be greater than zero.")


def place_order(symbol: str, qty: float, side: str, order_type: str, price: float | None,
                stop_price: float | None = None, time_in_force: str = "gfd",
                extended_hours: bool = False) -> dict[str, Any]:
    validate_order(symbol, qty, side, order_type, price, stop_price)

    if order_type == "market":
        if side == "buy":
            return rh.order_buy_fractional_by_quantity(symbol, qty, timeInForce=time_in_force, extendedHours=extended_hours)
        else:
            return rh.order_sell_fractional_by_quantity(symbol, qty, timeInForce=time_in_force, extendedHours=extended_hours)

    elif order_type == "limit":
        if side == "buy":
            return rh.order_buy_limit(symbol, qty, price, timeInForce=time_in_force, extendedHours=extended_hours)
        else:
            return rh.order_sell_limit(symbol, qty, price, timeInForce=time_in_force, extendedHours=extended_hours)

    elif order_type == "stop_loss":
        if side == "buy":
            return rh.order_buy_stop_loss(symbol, qty, stop_price, timeInForce=time_in_force, extendedHours=extended_hours)
        else:
            return rh.order_sell_stop_loss(symbol, qty, stop_price, timeInForce=time_in_force, extendedHours=extended_hours)

    elif order_type == "stop_limit":
        if side == "buy":
            return rh.order_buy_stop_limit(symbol, qty, price, stop_price, timeInForce=time_in_force, extendedHours=extended_hours)
        else:
            return rh.order_sell_stop_limit(symbol, qty, price, stop_price, timeInForce=time_in_force, extendedHours=extended_hours)

    elif order_type == "trailing_stop":
        if side == "buy":
            return rh.order_buy_trailing_stop(symbol, qty, stop_price, timeInForce=time_in_force, extendedHours=extended_hours)
        else:
            return rh.order_sell_trailing_stop(symbol, qty, stop_price, timeInForce=time_in_force, extendedHours=extended_hours)

    else:
        raise OrderValidationError(f"Unknown order_type: {order_type}. Use: market, limit, stop_loss, stop_limit, trailing_stop.")
