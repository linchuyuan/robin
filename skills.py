"""LangChain compatibility tools aligned to MCP JSON response contract."""
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from auth import get_session
from market_data import get_history, get_news
from portfolio import list_positions


class PortfolioTool(BaseTool):
    name = "get_portfolio"
    description = "Get open stock positions. Returns MCP-style JSON with positions, count, and result_text."

    def _run(self) -> dict:
        try:
            get_session()
            positions = list_positions() or []
            if not positions:
                return {"positions": [], "count": 0, "result_text": "No open positions found."}

            lines = []
            for pos in positions:
                lines.append(
                    f"{pos['symbol']}: {pos['quantity']} shares @ ${pos['average_buy_price']:.2f}"
                )
            return {
                "positions": positions,
                "count": len(positions),
                "result_text": "\n".join(lines),
            }
        except Exception as e:
            return {
                "positions": [],
                "count": 0,
                "error": str(e),
                "result_text": f"Error fetching portfolio: {str(e)}",
            }


class StockNewsTool(BaseTool):
    name = "get_stock_news"
    description = "Fetch recent stock news. Returns MCP-style JSON with articles and result_text."

    class Input(BaseModel):
        symbol: str = Field(description="The stock ticker symbol (e.g. AAPL, TSLA)")

    args_schema: Type[BaseModel] = Input

    def _run(self, symbol: str) -> dict:
        sym = str(symbol).upper()
        try:
            get_session()
            articles = get_news(sym) or []
            if not articles:
                return {
                    "symbol": sym,
                    "articles": [],
                    "result_text": f"No news found for {sym}.",
                }

            top = articles[:5]
            summary = []
            for art in top:
                summary.append(
                    f"- {art.get('title', 'N/A')} ({art.get('published_at', 'N/A')})\n"
                    f"  Link: {art.get('url', 'N/A')}"
                )
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
                "result_text": f"Error fetching news: {str(e)}",
            }


class StockHistoryTool(BaseTool):
    name = "get_stock_history"
    description = "Get historical OHLCV data. Returns MCP-style JSON with candles and CSV text."

    class Input(BaseModel):
        symbol: str = Field(description="The stock ticker symbol")
        span: str = Field(default="week", description="Time span: day, week, month, year")
        interval: str = Field(default="day", description="Interval: 5minute, 10minute, hour, day")

    args_schema: Type[BaseModel] = Input

    def _run(self, symbol: str, span: str = "week", interval: str = "day") -> dict:
        sym = str(symbol).upper()
        try:
            get_session()
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
                    f"{point.get('begins_at')},{point.get('open_price')},{point.get('high_price')},"
                    f"{point.get('low_price')},{point.get('close_price')},{point.get('volume', 0)}"
                )
            csv_text = "\n".join(lines)
            return {
                "symbol": sym,
                "span": span,
                "interval": interval,
                "candles": data,
                "csv": csv_text,
                "result_text": csv_text,
            }
        except Exception as e:
            return {
                "symbol": sym,
                "span": span,
                "interval": interval,
                "candles": [],
                "csv": "",
                "error": str(e),
                "result_text": f"Error fetching history: {str(e)}",
            }


# Compatibility list ready to be bound to non-MCP LangChain agents.
tools = [PortfolioTool(), StockNewsTool(), StockHistoryTool()]
