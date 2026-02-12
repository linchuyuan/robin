"""MCP Server for Robinhood Skills."""
import argparse
from datetime import datetime

from fastmcp import FastMCP
from auth import get_session
from portfolio import list_positions
from market_data import get_history, get_news
from macro_news import get_macro_news
from orders import place_order
from yahoo_finance import get_yf_quote, get_yf_news, get_yf_options
from account import get_account_profile
from crypto import get_crypto_quote, get_crypto_positions, place_crypto_order
from order_history import get_order_history, get_order_detail
from robin_options import (
    get_option_chain as fetch_option_chain,
    get_option_expirations as fetch_option_expirations,
)
from sentiment import get_fear_and_greed, get_vix
from market_calendar import get_market_status, get_upcoming_holidays, get_early_closes
from reddit_data import fetch_reddit_posts, fetch_reddit_post_comments
from reddit_sentiment import (
    get_reddit_symbol_mentions as build_reddit_symbol_mentions,
    get_reddit_sentiment_snapshot as build_reddit_sentiment_snapshot,
    get_reddit_trending_tickers as build_reddit_trending_tickers,
)

import robin_stocks.robinhood as rh

# Create an MCP server
mcp = FastMCP("Robinhood")

@mcp.tool()
def get_pending_orders() -> str:
    """List all pending stock orders."""
    try:
        get_session()
        orders = rh.get_all_open_stock_orders()
        if not orders:
            return "No pending orders found."
        
        result = []
        for order in orders:
            symbol = order.get('symbol')
            if not symbol:
                try:
                    symbol = rh.get_symbol_by_url(order.get('instrument')) or 'N/A'
                except Exception:
                    symbol = order.get('instrument_id', 'N/A')
            price_str = order.get('price') or 'market'
            state = order.get('state', 'unknown')
            trigger = order.get('trigger', 'immediate')
            stop_price = order.get('stop_price')
            # Build trigger info string for stop orders
            trigger_str = ""
            if trigger == 'stop' and stop_price:
                trigger_str = f" | trigger: stop @ {stop_price}"
            elif trigger != 'immediate':
                trigger_str = f" | trigger: {trigger}"
            result.append(f"ID: {order['id']} | {order.get('side')} {order.get('quantity')} {symbol} @ {price_str} | type: {order.get('type', 'N/A')}{trigger_str} | state: {state}")
        return "\n".join(result)
    except Exception as e:
        return f"Error fetching orders: {str(e)}"

@mcp.tool()
def cancel_order(order_id: str) -> str:
    """Cancel a specific order by ID."""
    try:
        get_session()
        rh.cancel_stock_order(order_id)
        return f"Cancellation requested for order {order_id}"
    except Exception as e:
        return f"Error cancelling order: {str(e)}"

@mcp.tool()
def get_portfolio() -> dict:
    """Get the current user's open stock positions with detailed P/L.

    Returns structured JSON for reliable downstream parsing, plus `result_text` for readability.
    """
    try:
        get_session()
        positions = list_positions() or []
        if not positions:
            return {
                "positions": [],
                "count": 0,
                "result_text": "No open positions found.",
            }

        lines = []
        normalized = []
        for pos in positions:
            day_pl = f"{pos['intraday_profit_loss']:+.2f} ({pos['intraday_percent_change']:+.2f}%)"
            total_pl = f"{pos['equity_change']:+.2f} ({pos['percent_change']:+.2f}%)"
            line = (
                f"{pos['symbol']}: {pos['quantity']} shares @ ${pos['average_buy_price']:.2f} | "
                f"Equity: ${pos['equity']:.2f} | "
                f"Day P/L: {day_pl} | "
                f"Total P/L: {total_pl} | "
                f"P/E: {pos.get('pe_ratio', 'N/A')} | "
                f"Mkt Cap: {pos.get('market_cap', 'N/A')} | "
                f"52W High: {pos.get('high_52_weeks', 'N/A')} | "
                f"52W Low: {pos.get('low_52_weeks', 'N/A')}"
            )
            lines.append(line)
            normalized.append(pos)

        return {
            "positions": normalized,
            "count": len(normalized),
            "result_text": "\n".join(lines),
        }
    except Exception as e:
        return {
            "positions": [],
            "count": 0,
            "error": str(e),
            "result_text": f"Error fetching portfolio: {str(e)}",
        }

@mcp.tool()
def get_stock_news(symbol: str) -> dict:
    """Fetch recent news articles for a specific stock ticker.

    Returns a structured payload (JSON-serializable) so downstream agents can parse it.
    """
    try:
        get_session()
        sym = symbol.upper()
        articles = get_news(sym) or []

        top = articles[:5]
        lines = []
        if not top:
            lines.append(f"No news found for {sym}.")
        else:
            for art in top:
                lines.append(f"- {art.get('title', 'N/A')} ({art.get('published_at', 'N/A')})\n  Link: {art.get('url', 'N/A')}")

        return {
            "symbol": sym,
            "articles": top,
            "result_text": "\n".join(lines),
        }
    except Exception as e:
        return {
            "symbol": symbol.upper(),
            "articles": [],
            "error": str(e),
            "result_text": f"Error fetching news: {str(e)}",
        }

@mcp.tool()
def get_stock_history(symbol: str, span: str = "week", interval: str = "day") -> dict:
    """Get historical OHLCV price data for a stock.

    NOTE: This now returns a structured JSON payload with a `candles` array.
    A CSV string is also included for backwards compatibility.

    Args:
        symbol: Stock ticker (e.g. AAPL)
        span: Time span (day, week, month, 3month, year, 5year)
        interval: Data interval (5minute, 10minute, hour, day, week)
    """
    try:
        get_session()
        sym = symbol.upper()
        data = get_history(sym, interval, span) or []
        if not data:
            return {
                "symbol": sym,
                "span": span,
                "interval": interval,
                "candles": [],
                "csv": "",
                "result_text": f"No history found for {sym}.",
            }

        lines = ["Date,Open,High,Low,Close,Volume"]
        for point in data:
            lines.append(
                f"{point.get('begins_at')},{point.get('open_price')},{point.get('high_price')},{point.get('low_price')},{point.get('close_price')},{point.get('volume', 0)}"
            )

        return {
            "symbol": sym,
            "span": span,
            "interval": interval,
            "candles": data,
            "csv": "\n".join(lines),
            "result_text": "\n".join(lines),
        }
    except Exception as e:
        return {
            "symbol": symbol.upper(),
            "span": span,
            "interval": interval,
            "candles": [],
            "csv": "",
            "error": str(e),
            "result_text": f"Error fetching history: {str(e)}",
        }

@mcp.tool()
def execute_order(symbol: str, qty: float, side: str, order_type: str = "market",
                  price: float = None, stop_price: float = None,
                  time_in_force: str = "gfd", extended_hours: bool = False) -> str:
    """Place a stock order on Robinhood.
    
    Args:
        symbol: Stock ticker to trade (e.g. AAPL)
        qty: Quantity of shares to buy/sell
        side: 'buy' or 'sell'
        order_type: 'market', 'limit', 'stop_loss', 'stop_limit', or 'trailing_stop' (default: market)
        price: Limit price (required for limit and stop_limit orders)
        stop_price: Stop/trigger price (required for stop_loss, stop_limit); trail amount in $ (for trailing_stop)
        time_in_force: 'gfd' (good for day) or 'gtc' (good til cancelled). Default: gfd
        extended_hours: If true, allow execution in pre/after-market hours. Default: false
    """
    try:
        get_session()
        result = place_order(symbol.upper(), qty, side, order_type, price,
                             stop_price=stop_price, time_in_force=time_in_force,
                             extended_hours=extended_hours)
        return f"Order submitted: {result.get('id')}\nDetails: {result}"
    except Exception as e:
        return f"Error placing order: {str(e)}"

@mcp.tool()
def get_option_expirations(symbol: str) -> dict:
    """
    Fetch available option expiration dates for a symbol.

    Args:
        symbol: Stock ticker symbol
    """
    try:
        get_session()
        expirations = fetch_option_expirations(symbol)
        if not expirations:
            return {
                "symbol": symbol.upper(),
                "expirations": [],
                "result_text": f"No expiration dates found for {symbol.upper()}.",
            }

        return {
            "symbol": symbol.upper(),
            "expirations": expirations,
            "nearest_expiration": expirations[0],
            "result_text": f"Available expiration dates for {symbol.upper()}:\n" + "\n".join(expirations),
        }
    except Exception as e:
        return {
            "symbol": symbol.upper(),
            "expirations": [],
            "error": str(e),
            "result_text": f"Error fetching expiration dates: {str(e)}",
        }


@mcp.tool()
def get_option_chain(symbol: str, expiration_date: str, strikes: int = 5) -> dict:
    """
    Fetch option chain data from Robinhood with Greeks.

    Args:
        symbol: Stock ticker symbol
        expiration_date: Required expiration date (YYYY-MM-DD).
        strikes: Number of strikes above/below current price to show (default: 5).
    """
    try:
        if not expiration_date:
            return {
                "symbol": symbol.upper(),
                "error": "expiration_date is required (YYYY-MM-DD)",
                "calls": [],
                "puts": [],
                "result_text": "Error: expiration_date is required (YYYY-MM-DD).",
            }

        get_session()
        data = fetch_option_chain(symbol, expiration_date)

        current_price = float(data.get("current_price", 0.0) or 0.0)
        calls = data.get("calls", [])
        puts = data.get("puts", [])

        calls_below = sorted(
            [c for c in calls if float(c.get("strike", 0) or 0) < current_price],
            key=lambda x: float(x.get("strike", 0) or 0),
            reverse=True,
        )[:strikes]
        calls_above = sorted(
            [c for c in calls if float(c.get("strike", 0) or 0) >= current_price],
            key=lambda x: float(x.get("strike", 0) or 0),
        )[:strikes]
        selected_calls = sorted(calls_below + calls_above, key=lambda x: float(x.get("strike", 0) or 0))

        puts_below = sorted(
            [p for p in puts if float(p.get("strike", 0) or 0) < current_price],
            key=lambda x: float(x.get("strike", 0) or 0),
            reverse=True,
        )[:strikes]
        puts_above = sorted(
            [p for p in puts if float(p.get("strike", 0) or 0) >= current_price],
            key=lambda x: float(x.get("strike", 0) or 0),
        )[:strikes]
        selected_puts = sorted(puts_below + puts_above, key=lambda x: float(x.get("strike", 0) or 0))

        def fmt_line(opt: dict) -> str:
            return (
                f"Strike: {opt.get('strike')} | Bid: {float(opt.get('bid', 0) or 0):.2f} | "
                f"Ask: {float(opt.get('ask', 0) or 0):.2f} | Mid: {float(opt.get('price', 0) or 0):.2f} | "
                f"IV: {float(opt.get('implied_volatility', 0) or 0):.2f} | Vol: {opt.get('volume')} | "
                f"OI: {opt.get('open_interest')} | Delta: {float(opt.get('delta', 0) or 0):.3f} | "
                f"Gamma: {float(opt.get('gamma', 0) or 0):.3f} | Theta: {float(opt.get('theta', 0) or 0):.3f} | "
                f"Vega: {float(opt.get('vega', 0) or 0):.3f}"
            )

        lines = [
            f"Option Chain for {symbol} (Exp: {data.get('expiration_date')})",
            f"Current Price: {current_price}",
            "",
            "CALLS:",
            *[fmt_line(c) for c in selected_calls],
            "",
            "PUTS:",
            *[fmt_line(p) for p in selected_puts],
        ]

        return {
            "symbol": symbol.upper(),
            "expiration_date": data.get("expiration_date"),
            "current_price": current_price,
            "calls": selected_calls,
            "puts": selected_puts,
            "result_text": "\n".join(lines),
        }
    except Exception as e:
        return {
            "symbol": symbol.upper(),
            "error": str(e),
            "calls": [],
            "puts": [],
            "result_text": f"Error fetching options: {str(e)}",
        }

@mcp.tool()
def get_yf_stock_quote(symbol: str) -> dict:
    """Fetch real-time stock quote from Yahoo Finance with detailed market data.

    NOTE: Returns structured JSON for machine parsing, plus a `result_text` string.
    """
    try:
        quote = get_yf_quote(symbol)
        lines = [
            f"Symbol: {quote.get('symbol')}",
            f"Price: {quote.get('current_price')}",
            f"Previous Close: {quote.get('previous_close')}",
            f"Open: {quote.get('open')}",
            f"High: {quote.get('high')}",
            f"Low: {quote.get('low')}",
            f"Bid: {quote.get('bid')} | Ask: {quote.get('ask')}",
            f"Volume: {quote.get('volume')} | Avg Volume: {quote.get('average_volume')} | Relative Volume: {quote.get('relative_volume')}",
            f"Market Cap: {quote.get('market_cap')}",
            f"P/E Ratio: {quote.get('pe_ratio')} | Forward P/E: {quote.get('forward_pe')}",
            f"Dividend Yield: {quote.get('dividend_yield')}",
            f"Beta: {quote.get('beta')}",
            f"52W High: {quote.get('52_week_high')} | 52W Low: {quote.get('52_week_low')}",
            f"50-Day Avg: {quote.get('50_day_avg')} | 200-Day Avg: {quote.get('200_day_avg')}",
            f"Sector: {quote.get('sector')} | Industry: {quote.get('industry')}",
            f"Earnings Date: {quote.get('earnings_date', 'N/A')}",
            f"Profit Margins: {quote.get('profit_margins')} | Revenue Growth: {quote.get('revenue_growth')}",
            f"Short Ratio: {quote.get('short_ratio')}",
        ]
        return {
            "symbol": (quote.get('symbol') or str(symbol).upper()),
            "quote": quote,
            "result_text": "\n".join(lines),
        }
    except Exception as e:
        return {
            "symbol": str(symbol).upper(),
            "quote": {},
            "error": str(e),
            "result_text": f"Error fetching Yahoo Finance quote: {str(e)}",
        }

@mcp.tool()
def get_yf_stock_news(symbol: str) -> dict:
    """Fetch latest news from Yahoo Finance for a symbol.

    NOTE: Returns structured JSON for machine parsing, plus a `result_text` string.

    Args:
        symbol: Stock ticker symbol (e.g. AAPL)
    """
    sym = str(symbol).upper()
    try:
        news = get_yf_news(sym) or []
        top = news[:5]

        summary = []
        if not top:
            summary.append(f"No Yahoo Finance news found for {sym}.")
        else:
            for art in top:
                title = art.get('title') or 'No Title'
                publisher = art.get('publisher') or 'Unknown'
                link = art.get('link') or art.get('url') or '#'
                summary.append(f"- {title} ({publisher})\n  Link: {link}")

        return {
            "symbol": sym,
            "articles": top,
            "result_text": "\n".join(summary),
        }
    except Exception as e:
        return {
            "symbol": sym,
            "articles": [],
            "error": str(e),
            "result_text": f"Error fetching Yahoo Finance news: {str(e)}",
        }

@mcp.tool()
def get_yf_option_chain(symbol: str, expiration_date: str, strikes: int = 5) -> dict:
    """
    Fetch option chain data from Yahoo Finance.

    Args:
        symbol: Stock ticker symbol
        expiration_date: Required expiration date (YYYY-MM-DD).
        strikes: Number of strikes above/below current price to show (default: 5).
    """
    try:
        if not expiration_date:
            return {
                "symbol": symbol.upper(),
                "error": "expiration_date is required (YYYY-MM-DD)",
                "calls": [],
                "puts": [],
                "result_text": "Error: expiration_date is required (YYYY-MM-DD).",
            }

        data = get_yf_options(symbol, expiration_date)

        current_price = float(data.get("current_price", 0.0) or 0.0)
        calls = data.get("calls", [])
        puts = data.get("puts", [])

        calls_below = sorted(
            [c for c in calls if float(c.get("strike", 0) or 0) < current_price],
            key=lambda x: float(x.get("strike", 0) or 0),
            reverse=True,
        )[:strikes]
        calls_above = sorted(
            [c for c in calls if float(c.get("strike", 0) or 0) >= current_price],
            key=lambda x: float(x.get("strike", 0) or 0),
        )[:strikes]
        selected_calls = sorted(calls_below + calls_above, key=lambda x: float(x.get("strike", 0) or 0))

        puts_below = sorted(
            [p for p in puts if float(p.get("strike", 0) or 0) < current_price],
            key=lambda x: float(x.get("strike", 0) or 0),
            reverse=True,
        )[:strikes]
        puts_above = sorted(
            [p for p in puts if float(p.get("strike", 0) or 0) >= current_price],
            key=lambda x: float(x.get("strike", 0) or 0),
        )[:strikes]
        selected_puts = sorted(puts_below + puts_above, key=lambda x: float(x.get("strike", 0) or 0))

        lines = [
            f"Option Chain for {symbol} (Exp: {data.get('expiration_date')})",
            f"Current Price: {current_price}",
            "",
            "CALLS:",
            *[
                f"Strike: {c.get('strike')} | Bid: {c.get('bid')} | Ask: {c.get('ask')} | Vol: {c.get('volume')}"
                for c in selected_calls
            ],
            "",
            "PUTS:",
            *[
                f"Strike: {p.get('strike')} | Bid: {p.get('bid')} | Ask: {p.get('ask')} | Vol: {p.get('volume')}"
                for p in selected_puts
            ],
        ]

        return {
            "symbol": symbol.upper(),
            "expiration_date": data.get("expiration_date"),
            "current_price": current_price,
            "calls": selected_calls,
            "puts": selected_puts,
            "result_text": "\n".join(lines),
        }
    except Exception as e:
        return {
            "symbol": symbol.upper(),
            "error": str(e),
            "calls": [],
            "puts": [],
            "result_text": f"Error fetching options: {str(e)}",
        }

@mcp.tool()
def get_account_info() -> str:
    """Get account buying power and cash info."""
    try:
        get_session()
        profile = get_account_profile()
        return (
            f"Buying Power: {profile.get('buying_power')}\n"
            f"Total Cash: {profile.get('cash')}\n"
            f"Cash Available for Withdrawal: {profile.get('cash_available_for_withdrawal')}\n"
            f"Cash Held for Orders: {profile.get('cash_held_for_orders')}\n"
            f"Unsettled Funds: {profile.get('unsettled_funds')}\n"
            f"Total Equity: {profile.get('equity')}\n"
            f"Market Value: {profile.get('market_value')}"
        )
    except Exception as e:
        return f"Error fetching account info: {str(e)}"

@mcp.tool()
def get_crypto_price(symbol: str) -> str:
    """Fetch crypto quote.
    
    Args:
        symbol: Crypto ticker (e.g. BTC)
    """
    try:
        get_session()
        quote = get_crypto_quote(symbol)
        return (
            f"Symbol: {quote['symbol']}\n"
            f"Mark Price: {quote['mark_price']}\n"
            f"Bid: {quote['bid_price']}\n"
            f"Ask: {quote['ask_price']}\n"
            f"High: {quote['high_price']}\n"
            f"Low: {quote['low_price']}"
        )
    except Exception as e:
        return f"Error fetching crypto quote: {str(e)}"

@mcp.tool()
def get_crypto_holdings() -> str:
    """Get current crypto positions."""
    try:
        get_session()
        positions = get_crypto_positions()
        if not positions:
            return "No crypto positions found."
        
        result = []
        for pos in positions:
            result.append(f"{pos['symbol']}: {pos['quantity']} (Cost Basis: {pos['cost_basis']})")
        return "\n".join(result)
    except Exception as e:
        return f"Error fetching crypto holdings: {str(e)}"

@mcp.tool()
def execute_crypto_order(symbol: str, qty: float, side: str, order_type: str = "market", price: float = None) -> str:
    """Place a crypto order.
    
    Args:
        symbol: Crypto ticker (e.g. BTC)
        qty: Quantity to buy/sell
        side: 'buy' or 'sell'
        order_type: 'market' or 'limit' (default: market)
        price: Limit price (required if order_type is limit)
    """
    try:
        get_session()
        result = place_crypto_order(symbol, qty, side, order_type, price)
        return f"Crypto Order submitted: {result.get('id')}\nDetails: {result}"
    except Exception as e:
        return f"Error placing crypto order: {str(e)}"

@mcp.tool()
def get_stock_order_history(limit: int = 20, days: int = None, symbol: str = None) -> str:
    """Fetch history of stock orders with optional filtering.
    
    Args:
        limit: Max number of orders to return (default: 20)
        days: Only return orders from the last N days (optional)
        symbol: Filter to a specific ticker (optional)
    """
    try:
        get_session()
        orders = get_order_history()
        if not orders:
            return "No order history found."
        
        # Filter by days FIRST (before expensive symbol resolution)
        if days is not None:
            from datetime import timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            filtered = []
            for order in orders:
                created = order.get('created_at', '')
                if created:
                    try:
                        order_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                        if order_dt >= cutoff:
                            filtered.append(order)
                    except (ValueError, TypeError):
                        filtered.append(order)
            orders = filtered
        
        # Apply limit early to cap how many symbols we resolve
        orders = orders[:limit * 2] if len(orders) > limit * 2 else orders
        
        # Resolve symbols only for the filtered subset
        for order in orders:
            if not order.get('symbol'):
                try:
                    order['symbol'] = rh.get_symbol_by_url(order.get('instrument')) or 'N/A'
                except Exception:
                    order['symbol'] = 'N/A'
        
        # Filter by symbol if specified (after resolution)
        if symbol:
            symbol_upper = symbol.upper()
            orders = [o for o in orders if o.get('symbol', '').upper() == symbol_upper]
        
        if not orders:
            return "No matching orders found."
        
        result = []
        for order in orders[:limit]:
            sym = order.get('symbol', 'N/A')
            state = order.get('state', 'unknown')
            date = order.get('created_at', 'N/A')
            avg_price = order.get('average_price') or 'N/A'
            limit_price = order.get('price') or 'N/A'
            result.append(
                f"ID: {order.get('id')} | {date} | {sym} | {order.get('side')} {order.get('quantity')} | "
                f"state: {state} | avg_price: {avg_price} | limit_price: {limit_price} | "
                f"type: {order.get('type', 'N/A')} | reject_reason: {order.get('reject_reason') or 'None'}"
            )
        return "\n".join(result)
    except Exception as e:
        return f"Error fetching order history: {str(e)}"

@mcp.tool()
def get_order_details(order_id: str) -> str:
    """Fetch details of a specific order by UUID.
    
    Args:
        order_id: The UUID of the order
    """
    try:
        get_session()
        order = get_order_detail(order_id)
        if not order:
            return f"Order {order_id} not found."
            
        symbol = rh.get_symbol_by_url(order.get('instrument')) or 'N/A'
        
        trigger = order.get('trigger', 'immediate')
        stop_price = order.get('stop_price')
        details = [
            f"Order ID: {order.get('id')}",
            f"Symbol: {symbol}",
            f"State: {order.get('state')}",
            f"Side: {order.get('side')}",
            f"Quantity: {order.get('quantity')}",
            f"Limit Price: {order.get('price') or 'N/A'}",
            f"Stop Price: {stop_price or 'N/A'}",
            f"Trigger: {trigger}",
            f"Average Fill Price: {order.get('average_price') or 'N/A'}",
            f"Type: {order.get('type')}",
            f"Time in Force: {order.get('time_in_force', 'N/A')}",
            f"Reject Reason: {order.get('reject_reason') or 'None'}",
            f"Created At: {order.get('created_at')}",
            f"Updated At: {order.get('updated_at')}",
            f"Fees: {order.get('fees')}",
            f"Executions: {len(order.get('executions', []))}",
        ]
        for i, ex in enumerate(order.get('executions', []), 1):
            details.append(f"  Fill {i}: {ex.get('quantity')} shares @ ${ex.get('price')} at {ex.get('timestamp')}")
        return "\n".join(details)
    except Exception as e:
        return f"Error fetching order details: {str(e)}"

@mcp.tool()
def get_fundamentals(symbol: str) -> dict:
    """Get fundamental data for a stock (P/E, Market Cap, sector, etc).

    NOTE: Returns structured JSON for machine parsing, plus a `result_text` string.

    Args:
        symbol: Stock ticker (e.g. AAPL)
    """
    sym = str(symbol).upper()
    try:
        get_session()
        data = rh.get_fundamentals(sym)
        if not data or not isinstance(data, list) or len(data) == 0:
            return {
                "symbol": sym,
                "fundamentals": {},
                "error": "No fundamentals found",
                "result_text": f"No fundamentals found for {sym}.",
            }

        f = data[0] or {}

        # Supplement with Yahoo Finance for sector/industry/EPS (Robinhood doesn't always have these)
        sector = f.get('sector') or 'N/A'
        industry = f.get('industry') or 'N/A'
        eps = 'N/A'
        try:
            import yfinance as yf
            yf_info = yf.Ticker(sym).info
            if sector == 'N/A' or not sector:
                sector = yf_info.get('sector', 'N/A')
            if industry == 'N/A' or not industry:
                industry = yf_info.get('industry', 'N/A')
            eps = yf_info.get('trailingEps', 'N/A')
        except Exception:
            pass

        enriched = dict(f)
        enriched.setdefault('sector', sector)
        enriched.setdefault('industry', industry)
        enriched.setdefault('eps', eps)

        lines = [
            f"Symbol: {sym}",
            f"Sector: {sector}",
            f"Industry: {industry}",
            f"Market Cap: {f.get('market_cap')}",
            f"P/E Ratio: {f.get('pe_ratio')}",
            f"EPS: {eps}",
            f"Div Yield: {f.get('dividend_yield')}",
            f"Avg Volume: {f.get('average_volume')}",
            f"Shares Outstanding: {f.get('shares_outstanding', 'N/A')}",
            f"Float: {f.get('float', 'N/A')}",
            f"52 Wk High: {f.get('high_52_weeks')}",
            f"52 Wk Low: {f.get('low_52_weeks')}",
            f"Open: {f.get('open')}",
            f"High: {f.get('high')}",
            f"Low: {f.get('low')}",
            f"Description: {(f.get('description') or 'N/A')[:200]}",
        ]

        return {
            "symbol": sym,
            "fundamentals": enriched,
            "result_text": "\n".join(lines),
        }
    except Exception as e:
        return {
            "symbol": sym,
            "fundamentals": {},
            "error": str(e),
            "result_text": f"Error fetching fundamentals: {str(e)}",
        }

@mcp.tool()
def get_earnings_calendar(symbols: str) -> dict:
    """Get upcoming earnings dates for one or more symbols.

    Returns structured JSON for reliable downstream parsing, plus `result_text`.

    Args:
        symbols: Comma-separated tickers (e.g. "AAPL,MSFT,GOOGL")
    """
    import yfinance as yf
    from datetime import datetime as dt, timezone

    symbol_list = [s.strip().upper() for s in (symbols or "").split(",") if s.strip()]
    rows = []

    def fmt_date(value):
        try:
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return dt.fromtimestamp(value, tz=timezone.utc).strftime('%Y-%m-%d')
            # pandas Timestamp / datetime-like
            if hasattr(value, 'strftime'):
                return value.strftime('%Y-%m-%d')
            s = str(value).strip()
            if not s:
                return None
            # handle strings like '2026-02-25 00:00:00'
            return s[:10]
        except Exception:
            return None

    for sym in symbol_list:
        date_str = None
        error = None
        try:
            ticker = yf.Ticker(sym)
            info = ticker.info or {}

            earnings_ts = info.get("earningsTimestamp")
            earnings_dates = info.get("earningsDate")

            if earnings_ts:
                date_str = fmt_date(earnings_ts)
            elif earnings_dates:
                if isinstance(earnings_dates, (list, tuple)) and len(earnings_dates) > 0:
                    date_str = fmt_date(earnings_dates[0])
                else:
                    date_str = fmt_date(earnings_dates)
            else:
                # Fallback: calendar
                try:
                    cal = ticker.calendar
                    if cal is not None and hasattr(cal, 'empty') and not cal.empty:
                        # pandas DataFrame: common row/index names vary by yf versions
                        if hasattr(cal, 'index'):
                            idx = [str(i) for i in list(cal.index)]
                            target = next((i for i in idx if 'earnings' in i.lower()), None)
                            if target is not None:
                                val = cal.loc[target].iloc[0] if hasattr(cal.loc[target], 'iloc') else cal.loc[target]
                                date_str = fmt_date(val)
                    elif isinstance(cal, dict) and cal:
                        date_str = fmt_date(cal.get('Earnings Date') or cal.get('earningsDate'))
                except Exception:
                    pass

            if not date_str:
                error = "No earnings date found"
        except Exception as e:
            error = str(e)[:120]

        rows.append({
            "symbol": sym,
            "date": date_str,
            "error": error,
        })

    lines = []
    for r in rows:
        if r.get("date"):
            lines.append(f"{r['symbol']}: {r['date']}")
        elif r.get("error"):
            lines.append(f"{r['symbol']}: Error ({r['error']})")
        else:
            lines.append(f"{r['symbol']}: No earnings date found")

    return {
        "symbols": symbol_list,
        "rows": rows,
        "result": "\n".join(lines),
        "result_text": "\n".join(lines),
    }

@mcp.tool()
def get_market_sentiment() -> dict:
    """Get market sentiment (Fear & Greed Index and VIX).

    NOTE: Returns structured JSON for machine parsing, plus a `result_text` string.
    """
    fg = get_fear_and_greed()
    vix = get_vix()

    # Human-readable formatting for backwards compatibility
    output = []

    if isinstance(fg, dict) and "error" not in fg:
        ts = fg.get('timestamp')
        ts_str = "N/A"
        try:
            if ts:
                ts_str = str(ts).replace('T', ' ')[:19]
        except Exception:
            ts_str = str(ts)
        output.append("--- Fear & Greed Index ---")
        output.append(f"Score: {fg.get('score', 0):.0f} ({fg.get('rating', 'Unknown')})")
        output.append(f"Previous: {fg.get('previous_close', 0):.0f}")
        output.append(f"Updated: {ts_str}")
    else:
        output.append(f"Fear & Greed: Error ({fg.get('error') if isinstance(fg, dict) else fg})")

    output.append("")

    if isinstance(vix, dict) and "error" not in vix:
        output.append("--- VIX (Volatility Index) ---")
        output.append(f"Price: {vix.get('price')}")
        output.append(f"Change: {vix.get('change', 0):+.2f} ({vix.get('percent_change', 0):+.2f}%)")
        output.append(f"Day Range: {vix.get('day_low')} - {vix.get('day_high')}")
        output.append(f"52W Range: {vix.get('52_week_low')} - {vix.get('52_week_high')}")
    else:
        output.append(f"VIX: Error ({vix.get('error') if isinstance(vix, dict) else vix})")

    regime = None
    if isinstance(fg, dict) and 'rating' in fg:
        regime = fg.get('rating')

    return {
        "fear_and_greed": fg,
        "vix": vix,
        "regime": regime,
        "result_text": "\n".join(output),
    }

@mcp.tool()
def get_macro_news_headlines(limit: int = 10, only_today: bool = False) -> str:
    """Get latest macroeconomic news headlines (Aggregated).
    
    Args:
        limit: Number of news items to return (default: 10)
        only_today: If True, only return news published today (default: False)
    """
    news_items = get_macro_news(limit, only_today=only_today)
    if not news_items:
        msg = "No macro news found"
        if only_today:
            msg += " for today"
        return f"{msg}."
    
    if "error" in news_items[0]:
        return f"Error fetching news: {news_items[0]['error']}"
        
    output = []
    for item in news_items:
        output.append(f"- [{item.get('source', 'Unknown')}] {item['title']} ({item['published']})")
        output.append(f"  Link: {item['link']}")
        
    return "\n".join(output)

@mcp.tool()
def get_reddit_posts(
    query: str,
    subreddits: str = "wallstreetbets,stocks,investing,SecurityAnalysis",
    sort: str = "new",
    time_filter: str = "day",
    limit: int = 50,
) -> dict:
    """Fetch recent Reddit posts for a query across one or more subreddits.

    NOTE: Requires app credentials in env vars:
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
    """
    try:
        payload = fetch_reddit_posts(
            query=query,
            subreddits=subreddits,
            sort=sort,
            time_filter=time_filter,
            limit=limit,
        )
        posts = payload.get("posts", [])
        lines = [f"Fetched {len(posts)} Reddit posts for query: {query}"]
        for p in posts[:5]:
            lines.append(
                f"- [{p.get('subreddit')}] {p.get('title')} "
                f"(score={p.get('score')}, comments={p.get('num_comments')})"
            )
        payload["result_text"] = "\n".join(lines)
        return payload
    except Exception as e:
        return {
            "posts": [],
            "meta": {
                "query": query,
                "subreddits": [s.strip() for s in str(subreddits).split(",") if s.strip()],
                "sort": sort,
                "time_filter": time_filter,
                "limit": limit,
            },
            "error": str(e),
            "result_text": f"Error fetching Reddit posts: {str(e)}",
        }

@mcp.tool()
def get_reddit_post_comments(post_id: str, sort: str = "top", limit: int = 100) -> dict:
    """Fetch comments for a Reddit post by post id."""
    try:
        payload = fetch_reddit_post_comments(post_id=post_id, sort=sort, limit=limit)
        comments = payload.get("comments", [])
        lines = [f"Fetched {len(comments)} comments for post {post_id}."]
        for c in comments[:5]:
            lines.append(f"- score={c.get('score')}: {(c.get('body') or '')[:120]}")
        payload["result_text"] = "\n".join(lines)
        return payload
    except Exception as e:
        return {
            "comments": [],
            "meta": {"post_id": post_id, "sort": sort, "limit": limit},
            "error": str(e),
            "result_text": f"Error fetching Reddit comments: {str(e)}",
        }

@mcp.tool()
def get_reddit_symbol_mentions(
    symbols: str,
    subreddits: str = "wallstreetbets,stocks,investing",
    lookback_hours: int = 24,
    include_comments: bool = True,
    limit_posts: int = 100,
) -> dict:
    """Extract ticker mention counts and context from Reddit posts/comments."""
    try:
        return build_reddit_symbol_mentions(
            symbols=symbols,
            subreddits=subreddits,
            lookback_hours=lookback_hours,
            include_comments=include_comments,
            limit_posts=limit_posts,
        )
    except Exception as e:
        return {
            "window": {},
            "symbols": [],
            "data_quality": {},
            "error": str(e),
            "result_text": f"Error computing Reddit symbol mentions: {str(e)}",
        }

@mcp.tool()
def get_reddit_sentiment_snapshot(
    symbols: str,
    subreddits: str = "wallstreetbets,stocks,investing,SecurityAnalysis",
    lookback_hours: int = 24,
    baseline_days: int = 30,
    limit_posts: int = 200,
) -> dict:
    """Compute a normalized Reddit sentiment factor per symbol."""
    try:
        return build_reddit_sentiment_snapshot(
            symbols=symbols,
            subreddits=subreddits,
            lookback_hours=lookback_hours,
            baseline_days=baseline_days,
            limit_posts=limit_posts,
        )
    except Exception as e:
        return {
            "window": {},
            "symbols": [],
            "method": "reddit_v1",
            "error": str(e),
            "result_text": f"Error computing Reddit sentiment snapshot: {str(e)}",
        }

@mcp.tool()
def get_reddit_ticker_sentiment(
    tickers: str,
    subreddits: str = "wallstreetbets,stocks,investing,SecurityAnalysis",
    lookback_hours: int = 24,
    baseline_days: int = 30,
    limit_posts: int = 200,
) -> dict:
    """Compute Reddit sentiment for a manual comma-separated ticker list.

    Args:
        tickers: Comma-separated symbols (e.g. "AAPL,TSLA,NVDA")
    """
    try:
        return build_reddit_sentiment_snapshot(
            symbols=tickers,
            subreddits=subreddits,
            lookback_hours=lookback_hours,
            baseline_days=baseline_days,
            limit_posts=limit_posts,
        )
    except Exception as e:
        return {
            "window": {},
            "symbols": [],
            "method": "reddit_v1",
            "error": str(e),
            "result_text": f"Error computing Reddit ticker sentiment: {str(e)}",
        }

@mcp.tool()
def get_reddit_trending_tickers(
    subreddits: str = "wallstreetbets,stocks,investing",
    lookback_hours: int = 24,
    min_mentions: int = 15,
    limit: int = 20,
) -> dict:
    """Find fast-rising ticker mentions on Reddit."""
    try:
        return build_reddit_trending_tickers(
            subreddits=subreddits,
            lookback_hours=lookback_hours,
            min_mentions=min_mentions,
            limit=limit,
        )
    except Exception as e:
        return {
            "window": {},
            "trending": [],
            "data_quality": {},
            "error": str(e),
            "result_text": f"Error computing Reddit trending tickers: {str(e)}",
        }

@mcp.tool()
def get_timestamp() -> str:
    """Get the current server timestamp."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

@mcp.tool()
def get_market_session() -> dict:
    """Get current market session status (pre-market, regular, after-hours, closed), today's schedule, and next open/close times.

    NOTE: Returns structured JSON so agents can reliably parse `market_session_calendar`.
    A human-readable `result_text` is included for compatibility.
    """
    status = get_market_status()
    hols = get_upcoming_holidays(3)

    lines = []
    lines.append(f"Session: {status.get('session','').upper()}")
    lines.append(f"Time: {status.get('timestamp')}")
    lines.append(f"Trading Day: {'Yes' if status.get('is_trading_day') else 'No'}")

    if status.get('holiday'):
        lines.append(f"Reason: {status.get('holiday')}")

    if status.get('is_early_close'):
        lines.append("Early Close: Yes")

    s = status.get('schedule') or {}
    if s:
        lines.append(f"Pre-Market: {s.get('premarket_open')}")
        lines.append(f"Open: {s.get('regular_open')}")
        lines.append(f"Close: {s.get('regular_close')}")
        lines.append(f"After-Hours: until {s.get('afterhours_close')}")

    if status.get('next_open'):
        lines.append(f"Next Open: {status.get('next_open')}")
    if status.get('next_close'):
        lines.append(f"Next Close: {status.get('next_close')}")

    if hols:
        lines.append("")
        lines.append("Upcoming Holidays:")
        for h in hols:
            lines.append(f"  {h.get('date')} ({h.get('day')})")

    # This is the machine-parseable calendar payload
    market_session_calendar = {
        "timezone": "America/New_York",
        "session_date": status.get('date'),
        **status,
        "upcoming_holidays": hols,
    }

    return {
        "session": status.get('session'),
        "is_trading_day": status.get('is_trading_day'),
        "timestamp": status.get('timestamp'),
        "market_session_calendar": market_session_calendar,
        "result_text": "\n".join(lines),
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Robinhood MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse", "streamable-http"],
        default="sse",
        help="Transport protocol for the server",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host/address to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--path", default="/sse", help="HTTP path for the endpoint")

    args = parser.parse_args()
    mcp.run(transport=args.transport, host=args.host, port=args.port, path=args.path)
