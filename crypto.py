"""Crypto helpers for Robinhood CLI."""
from __future__ import annotations
from typing import Any, Dict, List
import robin_stocks.robinhood as rh

def get_crypto_quote(symbol: str) -> Dict[str, Any]:
    """
    Fetch crypto quote for a symbol.
    
    :param symbol: Crypto symbol (e.g. BTC, ETH)
    :return: Dictionary containing quote information
    """
    quote = rh.get_crypto_quote(symbol)
    return {
        "symbol": quote.get("symbol"),
        "mark_price": quote.get("mark_price"),
        "bid_price": quote.get("bid_price"),
        "ask_price": quote.get("ask_price"),
        "volume": quote.get("volume"),
        "high_price": quote.get("high_price"),
        "low_price": quote.get("low_price")
    }

def get_crypto_positions() -> List[Dict[str, Any]]:
    """
    Fetch all open crypto positions.
    
    :return: List of crypto position dictionaries
    """
    positions = rh.get_crypto_positions()
    results = []
    for pos in positions:
        qty = float(pos.get("quantity_available", "0"))
        if qty > 0:
            results.append({
                "symbol": pos.get("currency", {}).get("code", "Unknown"),
                "quantity": qty,
                "cost_basis": pos.get("cost_basis", {}).get("amount", "0"),
                "currency_id": pos.get("currency", {}).get("id")
            })
    return results

def place_crypto_order(symbol: str, qty: float, side: str, order_type: str = "market", price: float = None) -> Dict[str, Any]:
    """
    Place a crypto order.
    
    :param symbol: Crypto symbol (e.g. BTC)
    :param qty: Quantity to buy/sell
    :param side: 'buy' or 'sell'
    :param order_type: 'market' or 'limit'
    :param price: Limit price
    """
    if side == "buy":
        if order_type == "market":
            # Market buy by price amount (e.g. $10 of BTC) is safer/common in RH crypto
            # But users usually think in quantity. robin_stocks has order_buy_crypto_by_quantity
            return rh.order_buy_crypto_by_quantity(symbol, qty)
        elif order_type == "limit":
            if price is None:
                raise ValueError("Limit orders require a price.")
            return rh.order_buy_crypto_limit(symbol, qty, price)
    elif side == "sell":
        if order_type == "market":
            return rh.order_sell_crypto_by_quantity(symbol, qty)
        elif order_type == "limit":
            if price is None:
                raise ValueError("Limit orders require a price.")
            return rh.order_sell_crypto_limit(symbol, qty, price)
            
    raise ValueError(f"Invalid side {side} or order_type {order_type}")
