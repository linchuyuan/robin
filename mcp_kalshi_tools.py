"""Kalshi market-data MCP tool registrations."""
from __future__ import annotations

from kalshi import (
    get_kalshi_economic_context,
    get_kalshi_event,
    get_kalshi_market,
    get_kalshi_stock_context,
    list_kalshi_markets,
    search_kalshi_markets,
    summarize_markets,
)


def register_kalshi_tools(mcp) -> None:
    @mcp.tool()
    def get_kalshi_markets(
        query: str = "",
        status: str = "open",
        limit: int = 25,
        max_pages: int = 3,
    ) -> dict:
        """
        Browse open Kalshi markets for macro, global, sector, or ticker-related trading context.

        Args:
            query: Optional text query to match against market ticker/title/subtitle/category.
            status: Kalshi market status filter, usually "open".
            limit: Max matching markets to return.
            max_pages: Number of Kalshi market-list pages to scan when query is provided.
        """
        try:
            if query:
                payload = search_kalshi_markets(query, status=status, limit=limit, max_pages=max_pages)
                header = f"Kalshi markets matching '{query}'"
            else:
                payload = list_kalshi_markets(status=status, limit=limit)
                payload["query"] = ""
                payload["source"] = "kalshi_public_api"
                header = f"Kalshi {status or 'all'} markets"
            payload["result_text"] = summarize_markets(payload.get("markets", []), header=header)
            return payload
        except Exception as e:
            return {
                "query": query,
                "status": status,
                "markets": [],
                "count": 0,
                "error": str(e),
                "result_text": f"Error fetching Kalshi markets: {str(e)}",
            }

    @mcp.tool()
    def get_kalshi_market_detail(ticker: str, include_orderbook: bool = True, depth: int = 10) -> dict:
        """
        Get a specific Kalshi market by ticker, optionally including orderbook depth.

        Args:
            ticker: Kalshi market ticker.
            include_orderbook: Include orderbook data for liquidity/price context.
            depth: Orderbook depth, capped by the helper.
        """
        try:
            payload = get_kalshi_market(ticker, include_orderbook=include_orderbook, depth=depth)
            market = payload.get("market") or {}
            lines = [
                f"{market.get('ticker')}: {market.get('title')}",
                f"Status: {market.get('status')} | Event: {market.get('event_ticker')} | Series: {market.get('series_ticker')}",
                f"Yes bid/ask: {market.get('yes_bid')}/{market.get('yes_ask')}c | Last: {market.get('last_price')}c",
                f"Volume: {market.get('volume')} | Open interest: {market.get('open_interest')} | Liquidity: {market.get('liquidity')}",
                f"Close time: {market.get('close_time')}",
            ]
            if include_orderbook and payload.get("orderbook"):
                lines.append("Orderbook included in structured response.")
            payload["result_text"] = "\n".join(lines)
            return payload
        except Exception as e:
            return {
                "ticker": str(ticker or "").upper(),
                "market": None,
                "error": str(e),
                "result_text": f"Error fetching Kalshi market detail: {str(e)}",
            }

    @mcp.tool()
    def get_kalshi_event_detail(event_ticker: str) -> dict:
        """
        Get Kalshi event detail by event ticker.

        Args:
            event_ticker: Kalshi event ticker from a market response.
        """
        try:
            payload = get_kalshi_event(event_ticker)
            event = payload.get("event") or {}
            markets = payload.get("markets") or []
            payload["result_text"] = (
                f"{event.get('event_ticker')}: {event.get('title')}\n"
                f"Category: {event.get('category')} | Series: {event.get('series_ticker')} | "
                f"Markets: {len(markets)}"
            )
            return payload
        except Exception as e:
            return {
                "event_ticker": str(event_ticker or "").upper(),
                "event": None,
                "error": str(e),
                "result_text": f"Error fetching Kalshi event detail: {str(e)}",
            }

    @mcp.tool()
    def get_kalshi_economic_market_context(topic: str = "all", status: str = "open", limit: int = 25) -> dict:
        """
        Collect Kalshi prediction-market context for macro/global market questions.

        Topics include: all, global, economic, inflation, fed, jobs, growth, energy.
        """
        try:
            payload = get_kalshi_economic_context(topic=topic, status=status, limit=limit)
            payload["result_text"] = summarize_markets(
                payload.get("markets", []),
                header=f"Kalshi economic context for {payload.get('topic')}",
            )
            return payload
        except Exception as e:
            return {
                "topic": topic,
                "markets": [],
                "count": 0,
                "error": str(e),
                "result_text": f"Error fetching Kalshi economic context: {str(e)}",
            }

    @mcp.tool()
    def get_kalshi_stock_market_context(
        symbol: str,
        company_name: str = "",
        status: str = "open",
        limit: int = 20,
    ) -> dict:
        """
        Collect Kalshi markets relevant to a stock ticker plus broad macro conditions.

        This is read-only context for an AI stock-trading agent. It does not place Kalshi trades.

        Args:
            symbol: Stock or ETF ticker, e.g. AAPL, NVDA, SPY.
            company_name: Optional company name to improve search recall.
            status: Kalshi market status filter, usually "open".
            limit: Max markets to return.
        """
        try:
            payload = get_kalshi_stock_context(
                symbol=symbol,
                company_name=company_name,
                status=status,
                limit=limit,
            )
            payload["result_text"] = summarize_markets(
                payload.get("markets", []),
                header=f"Kalshi stock-market context for {payload.get('symbol')}",
            )
            return payload
        except Exception as e:
            return {
                "symbol": str(symbol or "").upper(),
                "markets": [],
                "count": 0,
                "error": str(e),
                "result_text": f"Error fetching Kalshi stock context: {str(e)}",
            }
