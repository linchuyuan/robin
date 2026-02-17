"""Account helpers for Robinhood CLI."""
from __future__ import annotations
from typing import Any, Dict
import robin_stocks.robinhood as rh

def get_account_profile() -> Dict[str, Any]:
    """
    Fetch the account profile including buying power and cash balances.
    
    :return: Dictionary containing account profile information
    """
    profile = rh.load_account_profile()
    
    # Fetch portfolio profile for equity/market value
    try:
        portfolio = rh.load_portfolio_profile()
    except Exception:
        portfolio = {}

    equity_previous_close = (
        portfolio.get("equity_previous_close")
        or portfolio.get("adjusted_equity_previous_close")
        or profile.get("equity_previous_close")
    )
    return {
        "buying_power": profile.get("buying_power"),
        "cash": profile.get("cash"),
        "cash_available_for_withdrawal": profile.get("cash_available_for_withdrawal"),
        "cash_held_for_orders": profile.get("cash_held_for_orders"),
        "unsettled_funds": profile.get("unsettled_funds"),
        "portfolio_cash": profile.get("portfolio_cash"),
        "equity": portfolio.get("equity"),
        "market_value": portfolio.get("market_value"),
        "equity_previous_close": equity_previous_close,
        "extended_hours_equity": portfolio.get("extended_hours_equity"),
        "extended_hours_market_value": portfolio.get("extended_hours_market_value"),
    }
