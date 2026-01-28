"""MCP Server for Robinhood Skills."""
from fastmcp import FastMCP
from auth import get_session
from portfolio import list_positions
from market_data import get_history, get_news
from orders import place_order

# Create an MCP server
mcp = FastMCP("Robinhood")

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

if __name__ == "__main__":
    mcp.run()
