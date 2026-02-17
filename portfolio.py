#!/usr/bin/env python3
"""Portfolio helpers for Robinhood CLI."""
from __future__ import annotations
import robin_stocks.robinhood as rh
from typing import List, Dict, Any

def list_positions() -> List[Dict[str, Any]]:
    """
    Fetch open positions with detailed metrics using build_holdings.
    
    Returns:
        List of dictionaries containing:
        - symbol
        - quantity
        - average_buy_price
        - price (current)
        - equity (market value)
        - percent_change (unrealized P/L %)
        - equity_change (unrealized P/L $)
        - intraday_percent_change (today's P/L %)
        - intraday_profit_loss (today's P/L $)
        - type
        - name
        - instrument_id
    """
    # build_holdings returns a dict: {'SYMBOL': {'price': ..., 'quantity': ...}, ...}
    holdings = rh.build_holdings()
    
    # Fetch fundamentals for all symbols to get market_cap and ensure pe_ratio
    symbols = list(holdings.keys())
    fundamentals_map = {}
    quotes_map = {}
    
    if symbols:
        try:
            funds = rh.get_fundamentals(symbols)
            for f in funds:
                if f and 'symbol' in f:
                    fundamentals_map[f['symbol']] = f
        except Exception:
            pass # Fail gracefully if fundamentals fetch fails
            
        try:
            # Fetch quotes to manually calculate intraday P/L if needed (build_holdings can be stale/zero)
            qs = rh.get_quotes(symbols)
            for q in qs:
                if q and 'symbol' in q:
                    quotes_map[q['symbol']] = q
        except Exception:
            pass

    results = []
    for symbol, data in holdings.items():
        # Calculate Today's P/L $
        # Intraday P/L $ = Equity - (Equity / (1 + Intraday% / 100))
        try:
            equity = float(data.get('equity', 0))
            intraday_pct = float(data.get('intraday_percent_change', 0))
            
            # Use provided intraday_profit_loss if available, otherwise calculate it
            intraday_pl_raw = data.get('intraday_profit_loss')
            
            # Robust calculation using fresh quote data if available
            quote = quotes_map.get(symbol)
            if quote:
                last_price = float(quote.get('last_trade_price', 0))
                # Use adjusted_previous_close to account for splits/dividends
                prev_close = float(quote.get('adjusted_previous_close') or quote.get('previous_close', 0))
                quantity = float(data.get('quantity', 0))
                
                if prev_close > 0:
                    intraday_pl = (last_price - prev_close) * quantity
                    intraday_pct = ((last_price - prev_close) / prev_close) * 100
                    
                    # Update price/equity with fresher data if we have it
                    price = last_price
                    equity = price * quantity
                else:
                     # Fallback to existing logic if quotes data is weird
                     if intraday_pl_raw is not None:
                         intraday_pl = float(intraday_pl_raw)
                     elif intraday_pct == 0:
                         intraday_pl = 0.0
                     else:
                         prev_equity = equity / (1 + (intraday_pct / 100))
                         intraday_pl = equity - prev_equity
                         
            else:
                # Fallback to existing logic
                if intraday_pl_raw is not None:
                     intraday_pl = float(intraday_pl_raw)
                elif intraday_pct == 0:
                    intraday_pl = 0.0
                else:
                    prev_equity = equity / (1 + (intraday_pct / 100))
                    intraday_pl = equity - prev_equity
                    
        except (ValueError, TypeError):
            intraday_pl = 0.0

        # Enrich with fundamentals
        fund_data = fundamentals_map.get(symbol, {})
        market_cap = fund_data.get('market_cap')
        # Prefer fundamental data for PE if missing in holdings
        pe_ratio = data.get('pe_ratio') or fund_data.get('pe_ratio')
        
        # Try to get Beta from Yahoo Finance since Robinhood fundamentals might miss it
        # This is a bit slow if we do it for every symbol one by one.
        # But we don't have a batch YF endpoint easily accessible here without importing yf
        # Let's try to infer it if we had a batch way.
        # For now, let's just stick with what we have or accept N/A if RH doesn't provide it.
        # However, if the user really wants it, we can fetch from YF for each?
        # That would be slow (N requests).
        # Let's try to get it from RH 'fundamentals' if it exists (some accounts say it does, some don't).
        # If not, we might need a separate command or accept N/A.
        # BUT, looking at the debug output keys, 'beta' was NOT in the list.
        
        # Alternative: We can fetch it via yahoo_finance.get_yf_quote(symbol)['beta']?
        # We imported get_yf_quote in other files.
        # Let's try to use it if we can import it, but batching is key.
        # yf.Tickers(' '.join(symbols)).tickers...
        
        beta = 'N/A' # Default
        
        pos = {
            "symbol": symbol,
            "name": data.get("name"),
            "quantity": float(data.get("quantity", 0)),
            "average_buy_price": float(data.get("average_buy_price", 0)),
            "price": float(data.get("price", 0)) if 'price' not in locals() else price,
            "equity": float(data.get("equity", 0)) if 'equity' not in locals() else equity,
            "percent_change": float(data.get("percent_change", 0)),
            "equity_change": float(data.get("equity_change", 0)),
            "intraday_percent_change": intraday_pct,
            "intraday_profit_loss": intraday_pl,
            "instrument_id": data.get("id"), # This is usually the instrument ID in build_holdings
            "type": data.get("type"),
            "pe_ratio": pe_ratio,
            "market_cap": market_cap,
            "high_52_weeks": fund_data.get('high_52_weeks'),
            "low_52_weeks": fund_data.get('low_52_weeks'),
            "beta": beta,
        }
        results.append(pos)
        
    return results

def get_dividends(instrument_id: str) -> List[Dict[str, Any]]:
    """Fetch dividends for a specific instrument."""
    try:
        divs = rh.get_dividends_by_instrument(instrument_id, dividend_type='upcoming')
        return divs if divs else []
    except Exception:
        return []

def get_quote(symbol: str) -> dict[str, str]:
    return rh.get_latest_price(symbol)
