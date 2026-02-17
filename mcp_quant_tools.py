"""Quant-related MCP tool registrations."""
from __future__ import annotations

from quant import (
    get_peers as get_symbol_peer_candidates,
    get_portfolio_correlation,
    get_sector_performance as calculate_sector_performance,
    get_technical_indicators as calculate_technical_indicators,
)


def register_quant_tools(mcp) -> None:
    @mcp.tool()
    def get_technical_indicators_tool(symbol: str) -> dict:
        """
        Calculate technical indicators (RSI, SMA, ATR, Returns, Rel Vol) for a symbol.
        Use this to get pre-calculated features for quant scoring.
        """
        result = calculate_technical_indicators(symbol)
        sym = str(symbol).upper()
        if result.get("error"):
            return {
                "symbol": sym,
                "error": result.get("error"),
                "result_text": f"Error computing technical indicators for {sym}: {result.get('error')}",
            }
        return {
            **result,
            "result_text": (
                f"{sym} technicals | Price: {result.get('price')} | RSI14: {result.get('rsi_14')} | "
                f"SMA50: {result.get('sma_50')} | SMA200: {result.get('sma_200')} | "
                f"ATR14: {result.get('atr_14')} | Ret5d: {result.get('return_5d')} | "
                f"Ret20d: {result.get('return_20d')} | RelVol: {result.get('relative_volume')} | "
                f"RS%vsSPY: {result.get('rs_spy_percentile')} | "
                f"ATRStopDist: {(result.get('volatility_sizing') or {}).get('atr_stop_dist')} | "
                f"Shares/1kRisk: {(result.get('volatility_sizing') or {}).get('suggested_shares_per_1k_risk')}"
            ),
        }

    @mcp.tool()
    def get_sector_performance_tool() -> dict:
        """
        Get 5-day performance of major sector ETFs to identify leaders/laggards.
        Returns a list of sectors sorted by performance.
        """
        results = calculate_sector_performance()
        if not results:
            return {"sectors": [], "count": 0, "result_text": "No sector data found."}

        if isinstance(results[0], dict) and "error" in results[0]:
            return {"sectors": [], "error": results[0]["error"], "result_text": f"Error: {results[0]['error']}"}

        lines = ["Sector Performance (5-Day):"]
        for item in results:
            lines.append(f"{item['symbol']} ({item['name']}): {item['return_5d']:.2%}")

        return {
            "sectors": results,
            "count": len(results),
            "result_text": "\n".join(lines),
        }

    @mcp.tool()
    def get_symbol_peers(symbol: str) -> dict:
        """
        Get peer ticker candidates plus sector/industry classification.
        """
        sym = str(symbol).upper()
        result = get_symbol_peer_candidates(symbol)
        if result.get("error"):
            return {
                "symbol": sym,
                "sector": None,
                "industry": None,
                "peers": [],
                "count": 0,
                "error": result.get("error"),
                "result_text": f"Error fetching peers for {sym}: {result.get('error')}",
            }
        if not result.get("result_text"):
            peers = result.get("peers") or []
            result["result_text"] = (
                f"{sym} peers: " + ", ".join(p.get("symbol", "") for p in peers)
                if peers
                else f"No peers found for {sym}."
            )
        return result

    @mcp.tool()
    def get_portfolio_correlation_tool(symbols: str) -> dict:
        """
        Calculate correlation matrix for a list of symbols (comma-separated).
        Useful for checking portfolio diversification and risk concentration.
        Returns correlation matrix and identifies high-correlation pairs (>0.7).
        """
        sym_list = [s.strip().upper() for s in str(symbols or "").split(",") if s.strip()]
        if not sym_list:
            return {
                "symbols": [],
                "error": "symbols is required (comma-separated tickers, e.g. 'AAPL,MSFT,GOOG').",
                "result_text": "Error: symbols is required (comma-separated tickers).",
            }
        result = get_portfolio_correlation(sym_list)

        if result.get("error"):
            return {
                "symbols": sym_list,
                "error": result.get("error"),
                "result_text": f"Error calculating correlation: {result.get('error')}",
            }

        high_corr = result.get("high_correlation_pairs", [])
        effective_symbols = result.get("effective_symbols") or result.get("symbols") or []
        dropped_symbols = result.get("dropped_symbols") or []
        lines = [f"Correlation Analysis for {len(effective_symbols)} symbols:"]
        if high_corr:
            lines.append("High Correlation Pairs (>0.7):")
            for pair in high_corr:
                pair_symbols = pair.get("pair", [])
                value = pair.get("correlation")
                if isinstance(pair_symbols, list) and len(pair_symbols) == 2:
                    lines.append(f"  {pair_symbols[0]} <-> {pair_symbols[1]}: {value}")
        else:
            lines.append("No high correlation pairs found (>0.7). Portfolio looks diversified.")
        if dropped_symbols:
            lines.append(f"Dropped symbols (invalid/no data): {', '.join(dropped_symbols)}")

        result["result_text"] = "\n".join(lines)
        return result

