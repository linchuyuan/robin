"""Quant-related MCP tool registrations."""
from __future__ import annotations

from quant import (
    calculate_iv_rank,
    detect_unusual_options_activity,
    get_peers as get_symbol_peer_candidates,
    get_portfolio_correlation,
    get_portfolio_risk_summary as calculate_portfolio_risk,
    get_sector_performance as calculate_sector_performance,
    get_technical_indicators as calculate_technical_indicators,
    get_volume_velocity as calculate_volume_velocity,
)


def register_quant_tools(mcp) -> None:
    @mcp.tool()
    def get_technical_indicators_tool(symbol: str) -> dict:
        """
        Calculate technical indicators for a symbol: RSI, SMA (20/50/200), EMA (9/21),
        MACD (value/signal/histogram/crossover), Bollinger Bands (%B/bandwidth),
        ATR, VWAP, daily relative volume, relative strength vs SPY, IV rank, trend composite,
        and volatility-based position sizing.

        Note: relative_volume is daily volume vs prior 20 full-day average. For intraday
        participation, use get_volume_velocity_tool instead.
        """
        result = calculate_technical_indicators(symbol)
        sym = str(symbol).upper()
        if result.get("error"):
            return {
                "symbol": sym,
                "error": result.get("error"),
                "result_text": f"Error computing technical indicators for {sym}: {result.get('error')}",
            }
        macd = result.get("macd") or {}
        bb = result.get("bollinger") or {}
        trend = result.get("trend") or {}
        iv = result.get("iv_rank_data") or {}
        return {
            **result,
            "result_text": (
                f"{sym} technicals | Price: {result.get('price')} | Trend: {trend.get('label')} ({trend.get('score')}/5) | "
                f"RSI14: {result.get('rsi_14')} | "
                f"SMA20: {result.get('sma_20')} | SMA50: {result.get('sma_50')} | SMA200: {result.get('sma_200')} | "
                f"EMA9: {result.get('ema_9')} | EMA21: {result.get('ema_21')} | "
                f"MACD: {macd.get('value')} sig={macd.get('signal')} hist={macd.get('histogram')} xover={macd.get('crossover')} | "
                f"BB%B: {bb.get('pct_b')} BW: {bb.get('bandwidth')} | "
                f"ATR14: {result.get('atr_14')} | VWAP20: {result.get('vwap_20d')} | "
                f"Ret5d: {result.get('return_5d')} | Ret20d: {result.get('return_20d')} | "
                f"DailyRelVol: {result.get('relative_volume')} | RS%vsSPY: {result.get('rs_spy_percentile')} | "
                f"IVRank: {iv.get('iv_rank')} IVPctl: {iv.get('iv_percentile')} | "
                f"ATRStopDist: {(result.get('volatility_sizing') or {}).get('atr_stop_dist')} | "
                f"Shares/1kRisk: {(result.get('volatility_sizing') or {}).get('suggested_shares_per_1k_risk')}"
            ),
        }

    @mcp.tool()
    def get_volume_velocity_tool(
        symbol: str,
        interval: str = "5m",
        period: str = "5d",
        baseline_bars: int = 48,
        series_points: int = 24,
    ) -> dict:
        """
        Calculate intraday volume velocity as a time series.

        This compares each recent intraday bar's volume with the average volume of
        the prior N bars. Use it for intraday participation/acceleration checks
        instead of daily relative_volume.
        """
        result = calculate_volume_velocity(
            symbol=symbol,
            interval=interval,
            period=period,
            baseline_bars=baseline_bars,
            series_points=series_points,
        )
        sym = str(symbol).upper().strip()
        if result.get("error"):
            return {
                **result,
                "symbol": sym,
                "result_text": f"Error computing volume velocity for {sym}: {result.get('error')}",
            }

        latest = result.get("latest") or {}
        trend = result.get("trend") or {}
        result["result_text"] = (
            f"{sym} volume velocity ({result.get('interval')}, baseline={result.get('baseline_bars')} bars) | "
            f"Latest volume: {latest.get('volume')} | "
            f"Baseline: {latest.get('baseline_avg_volume')} [{latest.get('baseline_type')}, n={latest.get('same_slot_sample_size')}] | "
            f"Velocity ratio: {latest.get('velocity_ratio')} | "
            f"Z: {latest.get('velocity_z_score')} | "
            f"Class: {latest.get('classification')} | "
            f"Trend: {trend.get('label')} ({trend.get('ratio_delta_recent')})"
        )
        return result

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
            uses_fallback = any(p.get("source") != "yahoo_search" for p in peers)
            prefix = "SECTOR_FALLBACK_NOT_PEER_VALIDATED: " if uses_fallback else ""
            result["result_text"] = (
                prefix + f"{sym} peers: " + ", ".join(p.get("symbol", "") for p in peers)
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
            if dropped_symbols and len(dropped_symbols) >= max(1, len(sym_list) // 2):
                lines.append("No high correlation pairs found, but too many symbols were dropped to infer diversification.")
            else:
                lines.append("No high correlation pairs found (>0.7).")
        if dropped_symbols:
            lines.append(f"Dropped symbols (invalid/no data): {', '.join(dropped_symbols)}")

        result["result_text"] = "\n".join(lines)
        return result

    @mcp.tool()
    def get_iv_rank_tool(symbol: str) -> dict:
        """
        Get IV Rank and IV Percentile for a symbol (1-year lookback).
        IV Rank shows where current implied volatility sits relative to its 52-week range.
        High IV Rank (>50) favors selling premium; low IV Rank (<30) favors buying options.

        Args:
            symbol: Stock ticker (e.g. AAPL)
        """
        sym = str(symbol).upper().strip()
        result = calculate_iv_rank(sym)
        if result is None:
            return {
                "symbol": sym,
                "error": "Insufficient data to calculate IV rank",
                "result_text": f"Error: insufficient data to calculate IV rank for {sym}.",
            }
        warnings = list(result.get("warnings") or [])
        strategy_hint = None
        if result.get("volatility_metric") == "implied_volatility":
            strategy_hint = "sell_premium" if result["iv_rank"] > 50 else "buy_options"
        return {
            "symbol": sym,
            **result,
            "strategy_hint": strategy_hint,
            "result_text": (
                f"{sym} volatility analysis ({result.get('volatility_metric')}) | "
                f"Current: {result['iv_current']:.2%} | "
                f"52W High: {result['iv_52w_high']:.2%} | 52W Low: {result['iv_52w_low']:.2%} | "
                f"IV Rank: {result['iv_rank']:.1f} | IV Percentile: {result['iv_percentile']:.1f} | "
                f"Hint: {strategy_hint or 'none - proxy data only'}"
                + (f" | Warning: {'; '.join(warnings)}" if warnings else "")
            ),
        }

    @mcp.tool()
    def get_unusual_options_activity_basic_tool(symbol: str, expiration_date: str) -> dict:
        """
        Detect unusual options activity for a symbol at a given expiration.
        Flags strikes with volume/OI ratio > 2x and volume >= 500 contracts.
        Useful for detecting institutional flow and smart money positioning.

        Args:
            symbol: Stock ticker (e.g. AAPL)
            expiration_date: Expiration date (YYYY-MM-DD)
        """
        sym = str(symbol).upper().strip()
        if not expiration_date:
            return {
                "symbol": sym,
                "error": "expiration_date is required (YYYY-MM-DD)",
                "result_text": "Error: expiration_date is required.",
            }

        try:
            from yahoo_finance import get_yf_options

            data = get_yf_options(sym, expiration_date)
            calls = data.get("calls", [])
            puts = data.get("puts", [])
            current_price = float(data.get("current_price", 0) or 0)

            result = detect_unusual_options_activity(calls, puts, current_price)

            lines = [
                f"Unusual Options Activity for {sym} (Exp: {expiration_date})",
                f"Net Premium Bias: {result['net_premium_bias'].upper()}",
                f"Call Premium: ${result['total_call_premium_traded']:,.0f} | Put Premium: ${result['total_put_premium_traded']:,.0f}",
                f"P/C Premium Ratio: {result['put_call_premium_ratio']}",
                f"Unusual Strikes: {result['unusual_call_count']} calls, {result['unusual_put_count']} puts",
            ]
            for item in result.get("unusual_activity", [])[:5]:
                lines.append(
                    f"  {item['side'].upper()} ${item['strike']} | Vol: {item['volume']} OI: {item['open_interest']} "
                    f"V/OI: {item['vol_oi_ratio']}x | IV: {item['implied_volatility']:.2%} | "
                    f"Premium: ${item['premium_traded']:,.0f} | Moneyness: {item['moneyness']}%"
                )

            return {
                "symbol": sym,
                "expiration_date": expiration_date,
                "current_price": current_price,
                **result,
                "result_text": "\n".join(lines),
            }
        except Exception as e:
            return {
                "symbol": sym,
                "error": str(e),
                "result_text": f"Error detecting unusual options activity for {sym}: {e}",
            }

    @mcp.tool()
    def get_portfolio_concentration_summary_tool() -> dict:
        """
        Calculate portfolio-level risk metrics: position weights, sector concentration,
        HHI (Herfindahl index), total unrealized P/L, and concentration risk level.
        Requires authenticated Robinhood session.
        """
        try:
            from auth import get_session
            from portfolio import list_positions

            get_session()
            positions = list_positions() or []
            if not positions:
                return {
                    "positions": [],
                    "result_text": "No open positions for risk analysis.",
                }

            result = calculate_portfolio_risk(positions)
            if result.get("error"):
                return {
                    "error": result["error"],
                    "result_text": f"Error: {result['error']}",
                }

            conc = result.get("concentration", {})
            lines = [
                f"Portfolio Risk Summary | {result['position_count']} positions | Total: ${result['total_equity']:,.2f}",
                f"Unrealized P/L: ${result['total_unrealized_pnl']:+,.2f} | Day P/L: ${result['total_day_pnl']:+,.2f}",
                f"Concentration: {conc.get('risk_level', 'unknown').upper()} (HHI: {conc.get('hhi')}, Top: {conc.get('top_position_weight_pct')}%)",
                "",
                "Positions by weight:",
            ]
            for pos in result.get("positions", [])[:8]:
                lines.append(
                    f"  {pos['symbol']}: {pos['weight_pct']:.1f}% (${pos['equity']:,.2f}) | "
                    f"PnL: ${pos['unrealized_pnl']:+,.2f} | Day: ${pos['day_pnl']:+,.2f}"
                )
            if result.get("sector_breakdown"):
                lines.append("")
                lines.append("Sectors:")
                for sec in result["sector_breakdown"][:5]:
                    lines.append(f"  {sec['sector']}: {sec['weight_pct']:.1f}%")

            result["result_text"] = "\n".join(lines)
            return result
        except Exception as e:
            return {
                "error": str(e),
                "result_text": f"Error computing portfolio risk summary: {e}",
            }

    @mcp.tool()
    def get_multi_stock_quotes(symbols: str) -> dict:
        """
        Fetch Yahoo Finance quotes for multiple symbols in a single call.
        More efficient than calling get_yf_stock_quote repeatedly.

        Args:
            symbols: Comma-separated tickers (e.g. "AAPL,MSFT,GOOGL")
        """
        import yfinance as yf

        sym_list = [s.strip().upper() for s in str(symbols or "").split(",") if s.strip()]
        if not sym_list:
            return {
                "symbols": [],
                "error": "symbols is required (comma-separated tickers).",
                "result_text": "Error: symbols is required.",
            }

        quotes = []
        errors = []
        for sym in sym_list[:10]:  # Cap at 10 to avoid excessive API calls
            try:
                ticker = yf.Ticker(sym)
                info = ticker.info or {}
                quote = {
                    "symbol": sym,
                    "price": info.get("regularMarketPrice") or info.get("currentPrice"),
                    "regular_market_time": info.get("regularMarketTime"),
                    "previous_close": info.get("previousClose"),
                    "change_pct": None,
                    "volume": info.get("volume"),
                    "avg_volume": info.get("averageVolume"),
                    "market_cap": info.get("marketCap"),
                    "pe_ratio": info.get("trailingPE"),
                    "52w_high": info.get("fiftyTwoWeekHigh"),
                    "52w_low": info.get("fiftyTwoWeekLow"),
                    "beta": info.get("beta"),
                    "sector": info.get("sector"),
                    "data_quality": {
                        "source": "yfinance_ticker_info",
                        "quote_time": info.get("regularMarketTime"),
                        "warning": "Yahoo quote timing and delay status are provider-dependent.",
                    },
                }
                price = quote["price"]
                prev = quote["previous_close"]
                if price and prev and prev > 0:
                    quote["change_pct"] = round((price - prev) / prev * 100, 2)
                quotes.append(quote)
            except Exception as e:
                errors.append({"symbol": sym, "error": str(e)})

        lines = []
        for q in quotes:
            chg = f"{q['change_pct']:+.2f}%" if q.get("change_pct") is not None else "N/A"
            lines.append(
                f"{q['symbol']}: ${q['price']} ({chg}) | Vol: {q.get('volume')} | "
                f"MCap: {q.get('market_cap')} | P/E: {q.get('pe_ratio')} | "
                f"Sector: {q.get('sector')}"
            )
        for e in errors:
            lines.append(f"{e['symbol']}: Error ({e['error']})")

        return {
            "symbols": sym_list,
            "quotes": quotes,
            "errors": errors,
            "count": len(quotes),
            "result_text": "\n".join(lines),
        }
