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
    return {
        "buying_power": profile.get("buying_power"),
        "cash": profile.get("cash"),
        "cash_available_for_withdrawal": profile.get("cash_available_for_withdrawal"),
        "cash_held_for_orders": profile.get("cash_held_for_orders"),
        "unsettled_funds": profile.get("unsettled_funds"),
        "portfolio_cash": profile.get("portfolio_cash")
    }
