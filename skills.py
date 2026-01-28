"""AI Agent Skills for Robinhood."""
from typing import Optional, Type
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool

from auth import get_session
from portfolio import list_positions, get_quote
from market_data import get_history, get_news
from orders import place_order

# Ensure we are logged in before any tool runs
# In a real server context, you might handle session per-user differently.
try:
    get_session()
except Exception:
    pass


class PortfolioTool(BaseTool):
    name = "get_portfolio"
    description = "Get the current user's open stock positions, including quantity and average buy price."

    def _run(self) -> str:
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

class StockNewsTool(BaseTool):
    name = "get_stock_news"
    description = "Fetch recent news articles for a specific stock ticker symbol."

    class Input(BaseModel):
        symbol: str = Field(description="The stock ticker symbol (e.g. AAPL, TSLA)")

    args_schema: Type[BaseModel] = Input

    def _run(self, symbol: str) -> str:
        try:
            get_session()
            articles = get_news(symbol.upper())
            if not articles:
                return f"No news found for {symbol}."
            
            # Return top 3 for brevity in chat context
            summary = []
            for art in articles[:3]:
                summary.append(f"- {art['title']} ({art['published_at']})\n  Link: {art['url']}")
            return "\n".join(summary)
        except Exception as e:
            return f"Error fetching news: {str(e)}"

class StockHistoryTool(BaseTool):
    name = "get_stock_history"
    description = "Get historical price data for a stock over a specified period."

    class Input(BaseModel):
        symbol: str = Field(description="The stock ticker symbol")
        span: str = Field(default="week", description="Time span: day, week, month, year")
        interval: str = Field(default="day", description="Interval: 5minute, 10minute, hour, day")

    args_schema: Type[BaseModel] = Input

    def _run(self, symbol: str, span: str = "week", interval: str = "day") -> str:
        try:
            get_session()
            data = get_history(symbol.upper(), interval, span)
            if not data:
                return f"No history found for {symbol}."
            
            # Format as a simple CSV-like string for the LLM to analyze
            lines = ["Date,Open,Close"]
            for point in data:
                lines.append(f"{point['begins_at']},{point['open_price']},{point['close_price']}")
            return "\n".join(lines)
        except Exception as e:
            return f"Error fetching history: {str(e)}"

# List of tools ready to be bound to an agent
tools = [PortfolioTool(), StockNewsTool(), StockHistoryTool()]
