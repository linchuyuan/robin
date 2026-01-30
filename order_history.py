"""Order history helpers for Robinhood CLI."""
from __future__ import annotations
from typing import Any, Dict, List
import robin_stocks.robinhood as rh

def get_order_history() -> List[Dict[str, Any]]:
    """
    Fetch all stock order history.
    
    :return: List of order dictionaries
    """
    # get_all_stock_orders returns a list of dictionaries
    return rh.get_all_stock_orders()

def get_order_detail(order_id: str) -> Dict[str, Any]:
    """
    Fetch details for a specific order by ID.
    
    :param order_id: The UUID of the order
    :return: Dictionary containing order details
    """
    return rh.get_stock_order_info(order_id)
