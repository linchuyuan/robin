"""Order-building helpers."""

from __future__ import annotations

from typing import Any

import robin_stocks.robinhood as rh


class OrderValidationError(ValueError):
    pass


def validate_order(symbol: str, qty: float, side: str, order_type: str, price: float | None) -> None:
    if side not in {"buy", "sell"}:
        raise OrderValidationError("--side must be 'buy' or 'sell'.")
    if order_type == "limit" and price is None:
        raise OrderValidationError("Limit orders require --price.")
    if order_type == "market" and qty <= 0:
        raise OrderValidationError("Quantity must be greater than zero.")


def build_payload(symbol: str, qty: float, side: str, order_type: str, price: float | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": symbol,
        "quantity": qty,
        "side": side,
        "order_type": order_type,
        "time_in_force": "gfd",
    }
    if order_type == "limit":
        payload["limit_price"] = price
    return payload


def place_order(symbol: str, qty: float, side: str, order_type: str, price: float | None, session: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_order(symbol, qty, side, order_type, price)
    order_payload = build_payload(symbol, qty, side, order_type, price)
    if session:
        rh.set_session(session)
    if order_type == "market":
        return rh.order_buy_fractional_by_quantity(symbol, qty) if side == "buy" else rh.order_sell_fractional_by_quantity(symbol, qty)
    return rh.order_buy_symbol(symbol, qty, "limit", price) if side == "buy" else rh.order_sell_symbol(symbol, qty, "limit", price)
