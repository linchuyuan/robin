"""Robinhood Options helpers."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import robin_stocks.robinhood as rh

def get_implied_volatility(symbol: str) -> float | None:
    """Fetch current implied volatility for a symbol."""
    try:
        # We can get IV from the chain or options market data
        # Getting it from the nearest expiration's ATM option is a common proxy
        chains = rh.get_chains(symbol)
        if not chains or 'expiration_dates' not in chains:
            return None
            
        # Get the nearest expiration
        nearest_date = chains['expiration_dates'][0]
        
        # Get options for that date
        options = rh.find_options_by_expiration(symbol, nearest_date)
        if not options:
            return None
            
        # Filter for active options
        options = [o for o in options if o.get('state') == 'active']
        
        # Calculate IV average from ATM options
        # We need current price first, but we can infer it or just take an average of high volume ones
        # A simpler way might be available if robin_stocks exposes 'market_data' directly
        
        # Let's try to find the option with strike closest to market price? 
        # Without market price, we can just average the IV of all options or a subset?
        # Better: let's just return the IV of the first option for now, or None if too complex to calculate accurately here without quote
        
        # Actually, let's fetch quote to find ATM
        quote = rh.get_quotes(symbol)[0]
        price = float(quote['last_trade_price'])
        
        # Find ATM call
        atm_option = min(options, key=lambda x: abs(float(x['strike_price']) - price))
        return float(atm_option.get('implied_volatility') or 0)
        
    except:
        return None

def get_option_chain(symbol: str, expiration_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Fetch options chain for a symbol from Robinhood, including Greeks.
    
    :param symbol: Stock ticker symbol
    :param expiration_date: Specific expiration date (YYYY-MM-DD). If None, uses the nearest one.
    :return: Dictionary containing expiration dates or option chain data
    """
    symbol = symbol.upper()
    
    # 1. Get all expiration dates
    expirations_data = rh.get_chains(symbol)
    if not expirations_data or 'expiration_dates' not in expirations_data:
        return {"expirations": []}
        
    all_expirations = expirations_data['expiration_dates']
    
    # If no date provided, return list of dates (or default to nearest?)
    # The CLI/MCP pattern usually lists dates if none provided.
    if not expiration_date:
        return {"expirations": all_expirations}
    
    if expiration_date not in all_expirations:
        raise ValueError(f"Invalid expiration date. Available: {', '.join(all_expirations[:5])}...")

    # 2. Get stock price for "near money" calculation
    try:
        quote = rh.get_quotes(symbol)[0]
        current_price = float(quote['last_trade_price'])
    except:
        current_price = 0.0

    # 3. Fetch options for the specific date
    # find_options_by_expiration returns a list of dicts with Greeks included
    options = rh.find_options_by_expiration(symbol, expiration_date)
    
    calls = []
    puts = []
    
    for opt in options:
        # Filter out invalid or inactive options if necessary
        if opt.get('state') != 'active':
            continue
            
        # Extract relevant data (use `or 0` to guard against explicit None values)
        item = {
            "strike": float(opt.get("strike_price") or 0),
            "price": float(opt.get("adjusted_mark_price") or 0),
            "bid": float(opt.get("bid_price") or 0),
            "ask": float(opt.get("ask_price") or 0),
            "volume": int(opt.get("volume") or 0),
            "open_interest": int(opt.get("open_interest") or 0),
            "implied_volatility": float(opt.get("implied_volatility") or 0),
            "delta": float(opt.get("delta") or 0),
            "gamma": float(opt.get("gamma") or 0),
            "theta": float(opt.get("theta") or 0),
            "vega": float(opt.get("vega") or 0),
            "rho": float(opt.get("rho") or 0),
            "type": opt.get("type")
        }
        
        if opt["type"] == "call":
            calls.append(item)
        elif opt["type"] == "put":
            puts.append(item)
            
    # Sort by strike price
    calls.sort(key=lambda x: x["strike"])
    puts.sort(key=lambda x: x["strike"])
    
    return {
        "symbol": symbol,
        "expiration_date": expiration_date,
        "current_price": current_price,
        "calls": calls,
        "puts": puts
    }
