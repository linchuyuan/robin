"""MCP Server for Robinhood Skills."""
import argparse

from fastmcp import FastMCP
from auth import get_session
from portfolio import list_positions
from market_data import get_history, get_news
from orders import place_order
from yahoo_finance import get_yf_quote, get_yf_news, get_yf_options
from account import get_account_profile

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
            result.append(f"ID: {order['id']} | {order['side']} {order['quantity']} {order['symbol']} @ {order.get('price', 'market')}")
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
def get_portfolio() -> str:
    """Get the current user's open stock positions."""
    try:
        get_session()
        positions = list_positions()
        if not positions:
            return "No open positions found."
        
        result = []
        for pos in positions:
            result.append(f"{pos['symbol']}: {pos['quantity']} shares @ ${pos['average_buy_price']}")
        return "\n".join(result)
    except Exception as e:
        return f"Error fetching portfolio: {str(e)}"

@mcp.tool()
def get_stock_news(symbol: str) -> str:
    """Fetch recent news articles for a specific stock ticker."""
    try:
        get_session()
        articles = get_news(symbol.upper())
        if not articles:
            return f"No news found for {symbol}."
        
        summary = []
        for art in articles[:5]:
            summary.append(f"- {art['title']} ({art['published_at']})\n  Link: {art['url']}")
        return "\n".join(summary)
    except Exception as e:
        return f"Error fetching news: {str(e)}"

@mcp.tool()
def get_stock_history(symbol: str, span: str = "week", interval: str = "day") -> str:
    """Get historical price data for a stock.
    
    Args:
        symbol: Stock ticker (e.g. AAPL)
        span: Time span (day, week, month, year)
        interval: Data interval (5minute, 10minute, hour, day)
    """
    try:
        get_session()
        data = get_history(symbol.upper(), interval, span)
        if not data:
            return f"No history found for {symbol}."
        
        lines = ["Date,Open,Close"]
        for point in data:
            lines.append(f"{point['begins_at']},{point['open_price']},{point['close_price']}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching history: {str(e)}"

@mcp.tool()
def execute_order(symbol: str, qty: float, side: str, order_type: str = "market", price: float = None) -> str:
    """Place a stock order on Robinhood.
    
    Args:
        symbol: Stock ticker to trade (e.g. AAPL)
        qty: Quantity of shares to buy/sell
        side: 'buy' or 'sell'
        order_type: 'market' or 'limit' (default: market)
        price: Limit price (required if order_type is limit)
    """
    try:
        get_session()
        result = place_order(symbol.upper(), qty, side, order_type, price)
        return f"Order submitted: {result.get('id')}\nDetails: {result}"
    except Exception as e:
        return f"Error placing order: {str(e)}"

@mcp.tool()
def get_yf_stock_quote(symbol: str) -> str:
    """Fetch real-time stock quote from Yahoo Finance."""
    try:
        quote = get_yf_quote(symbol)
        return (
            f"Symbol: {quote['symbol']}\n"
            f"Price: {quote['current_price']}\n"
            f"Open: {quote['open']}\n"
            f"High: {quote['high']}\n"
            f"Low: {quote['low']}\n"
            f"Volume: {quote['volume']}\n"
            f"Market Cap: {quote['market_cap']}\n"
            f"P/E Ratio: {quote['pe_ratio']}\n"
            f"Dividend Yield: {quote['dividend_yield']}"
        )
    except Exception as e:
        return f"Error fetching Yahoo Finance quote: {str(e)}"

@mcp.tool()
def get_yf_stock_news(symbol: str) -> str:
    """Fetch latest news from Yahoo Finance for a symbol."""
    try:
        news = get_yf_news(symbol)
        if not news:
            return f"No Yahoo Finance news found for {symbol}."
        
        summary = []
        for art in news[:5]:
            title = art.get('title', 'No Title')
            link = art.get('link', '#')
            publisher = art.get('publisher', 'Unknown')
            summary.append(f"- {title} ({publisher})\n  Link: {link}")
        return "\n".join(summary)
    except Exception as e:
        return f"Error fetching Yahoo Finance news: {str(e)}"

@mcp.tool()
def get_yf_option_chain(symbol: str, expiration_date: str = None) -> str:
    """
    Fetch option chain data from Yahoo Finance.
    
    Args:
        symbol: Stock ticker symbol
        expiration_date: Optional expiration date (YYYY-MM-DD). If omitted, lists available dates.
    """
    try:
        data = get_yf_options(symbol, expiration_date)
        
        if "expirations" in data and not "calls" in data:
            return f"Available expiration dates for {symbol}:\n" + "\n".join(data["expirations"])
        
        output = [f"Option Chain for {symbol} (Exp: {data['expiration_date']})"]
        current_price = data.get("current_price", 0.0)
        output.append(f"Current Price: {current_price}\n")
        
        output.append("CALLS (Top 5 near money):")
        calls = data.get("calls", [])
        calls.sort(key=lambda x: abs(float(x.get('strike', 0)) - current_price))
        for c in calls[:5]: # Simplified view
            output.append(f"Strike: {c.get('strike')} | Bid: {c.get('bid')} | Ask: {c.get('ask')} | Vol: {c.get('volume')}")
            
        output.append("\nPUTS (Top 5 near money):")
        puts = data.get("puts", [])
        puts.sort(key=lambda x: abs(float(x.get('strike', 0)) - current_price))
        for p in puts[:5]: # Simplified view
            output.append(f"Strike: {p.get('strike')} | Bid: {p.get('bid')} | Ask: {p.get('ask')} | Vol: {p.get('volume')}")
            
        return "\n".join(output)
    except Exception as e:
        return f"Error fetching options: {str(e)}"

@mcp.tool()
def get_account_info() -> str:
    """Get account buying power and cash info."""
    try:
        get_session()
        profile = get_account_profile()
        return (
            f"Buying Power: {profile.get('buying_power')}\n"
            f"Cash Available for Withdrawal: {profile.get('cash_available_for_withdrawal')}\n"
            f"Cash Held for Orders: {profile.get('cash_held_for_orders')}\n"
            f"Unsettled Funds: {profile.get('unsettled_funds')}"
        )
    except Exception as e:
        return f"Error fetching account info: {str(e)}"

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
