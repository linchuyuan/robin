import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _extract_payload(result) -> dict:
    """Extract dict payload from MCP call result across SDK variants."""
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured

    content = getattr(result, "content", None) or []
    for item in content:
        if isinstance(item, dict):
            if isinstance(item.get("json"), dict):
                return item["json"]
            text = item.get("text")
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    continue

        text = getattr(item, "text", None)
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

    raise AssertionError("Unable to extract JSON payload from MCP result.")


def _assert_common_contract(payload: dict, tool_name: str) -> None:
    _assert(isinstance(payload, dict), f"{tool_name}: payload must be dict")
    _assert("result_text" in payload, f"{tool_name}: missing result_text")


def _assert_option_shape(option: dict, tool_name: str) -> None:
    required_keys = [
        "strike",
        "price",
        "bid",
        "ask",
        "volume",
        "open_interest",
        "implied_volatility",
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
    ]
    for key in required_keys:
        _assert(key in option, f"{tool_name}: option item missing key '{key}'")


async def test_server() -> None:
    python_exe = sys.executable
    server_params = StdioServerParameters(
        command=python_exe,
        args=["server.py", "--transport", "stdio"],
        env=None,
    )

    print("Connecting to MCP server...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Connected!")

            tools = await session.list_tools()
            print(f"Found {len(tools.tools)} tools")

            print("Testing get_technical_indicators_tool...")
            tech_raw = await session.call_tool("get_technical_indicators_tool", arguments={"symbol": "AAPL"})
            tech = _extract_payload(tech_raw)
            _assert_common_contract(tech, "get_technical_indicators_tool")
            if "error" not in tech:
                for key in ("symbol", "price", "sma_50", "sma_200", "rsi_14", "atr_14", "rs_spy_percentile", "return_5d", "return_20d", "relative_volume", "volatility_sizing", "timestamp", "timezone"):
                    _assert(key in tech, f"get_technical_indicators_tool: missing key '{key}'")
                _assert(isinstance(tech["volatility_sizing"], dict), "volatility_sizing must be a dict")
                _assert("suggested_shares_per_1k_risk" in tech["volatility_sizing"], "volatility_sizing missing suggested_shares")

            print("Testing get_yf_stock_quote...")
            yf_quote_raw = await session.call_tool("get_yf_stock_quote", arguments={"symbol": "AAPL"})
            yf_quote = _extract_payload(yf_quote_raw)
            _assert_common_contract(yf_quote, "get_yf_stock_quote")
            if "error" not in yf_quote:
                quote_data = yf_quote.get("quote", {})
                for key in ("symbol", "current_price", "short_percent_float", "held_percent_insiders"):
                    _assert(key in quote_data, f"get_yf_stock_quote: missing key '{key}' in quote object")

            print("Testing get_sector_performance_tool...")
            sector_raw = await session.call_tool("get_sector_performance_tool", arguments={})
            sector = _extract_payload(sector_raw)
            _assert_common_contract(sector, "get_sector_performance_tool")
            if "error" not in sector:
                _assert("sectors" in sector and isinstance(sector["sectors"], list), "get_sector_performance_tool: sectors must be list")

            print("Testing get_symbol_peers...")
            peers_raw = await session.call_tool("get_symbol_peers", arguments={"symbol": "MSFT"})
            peers = _extract_payload(peers_raw)
            _assert_common_contract(peers, "get_symbol_peers")
            for key in ("symbol", "peers", "count"):
                _assert(key in peers, f"get_symbol_peers: missing key '{key}'")

            print("Testing get_yf_option_expirations...")
            exp_raw = await session.call_tool("get_yf_option_expirations", arguments={"symbol": "AAPL"})
            expirations = _extract_payload(exp_raw)
            _assert_common_contract(expirations, "get_yf_option_expirations")
            _assert("expirations" in expirations and isinstance(expirations["expirations"], list), "get_yf_option_expirations: expirations must be list")

            if "error" not in expirations and expirations["expirations"]:
                expiration_date = expirations["expirations"][0]
                print(f"Testing get_yf_option_chain for {expiration_date}...")
                chain_raw = await session.call_tool(
                    "get_yf_option_chain",
                    arguments={"symbol": "AAPL", "expiration_date": expiration_date, "strikes": 3},
                )
                chain = _extract_payload(chain_raw)
                _assert_common_contract(chain, "get_yf_option_chain")
                for key in ("symbol", "expiration_date", "calls", "puts"):
                    _assert(key in chain, f"get_yf_option_chain: missing key '{key}'")
                if "error" not in chain:
                    _assert(isinstance(chain["calls"], list), "get_yf_option_chain: calls must be list")
                    _assert(isinstance(chain["puts"], list), "get_yf_option_chain: puts must be list")
                    _assert("sentiment_stats" in chain, "get_yf_option_chain: missing sentiment_stats")
                    _assert("greeks_estimation" in chain, "get_yf_option_chain: missing greeks_estimation")
                    stats = chain["sentiment_stats"]
                    for k in ("total_call_volume", "total_put_volume", "volume_put_call_ratio"):
                        _assert(k in stats, f"get_yf_option_chain: missing stat {k}")
                    if chain.get("warning"):
                        _assert("fallback_limit_per_side" in chain, "get_yf_option_chain warning path: missing fallback_limit_per_side")
                        _assert("truncated" in chain, "get_yf_option_chain warning path: missing truncated flag")
                    if chain["calls"]:
                        _assert_option_shape(chain["calls"][0], "get_yf_option_chain.calls")
                        call0 = chain["calls"][0]
                        if call0.get("delta") is not None:
                            _assert(call0["delta"] >= -0.05, "call delta should be near non-negative")
                        if call0.get("gamma") is not None:
                            _assert(call0["gamma"] >= 0, "call gamma should be non-negative")
                        if call0.get("vega") is not None:
                            _assert(call0["vega"] >= 0, "call vega should be non-negative")
                    if chain["puts"]:
                        _assert_option_shape(chain["puts"][0], "get_yf_option_chain.puts")
                        put0 = chain["puts"][0]
                        if put0.get("delta") is not None:
                            _assert(put0["delta"] <= 0.05, "put delta should be near non-positive")
                        if put0.get("gamma") is not None:
                            _assert(put0["gamma"] >= 0, "put gamma should be non-negative")
                        if put0.get("vega") is not None:
                            _assert(put0["vega"] >= 0, "put vega should be non-negative")

                print("Testing get_yf_option_chain invalid expiration handling...")
                invalid_raw = await session.call_tool(
                    "get_yf_option_chain",
                    arguments={"symbol": "AAPL", "expiration_date": "2099-01-01", "strikes": 3},
                )
                invalid_chain = _extract_payload(invalid_raw)
                _assert_common_contract(invalid_chain, "get_yf_option_chain_invalid_expiration")
                _assert(invalid_chain.get("error_code") == "invalid_expiration_date", "invalid expiration: missing/incorrect error_code")
                _assert("available_expirations" in invalid_chain, "invalid expiration: missing available_expirations")
                _assert(isinstance(invalid_chain["available_expirations"], list), "invalid expiration: available_expirations must be list")
                if invalid_chain["available_expirations"]:
                    _assert(
                        invalid_chain.get("suggested_expiration") == invalid_chain["available_expirations"][0],
                        "invalid expiration: suggested_expiration should be first available date",
                    )
            else:
                print("Skipping get_yf_option_chain call: no Yahoo expirations available.")

            print("Testing get_portfolio_correlation_tool...")
            corr_raw = await session.call_tool("get_portfolio_correlation_tool", arguments={"symbols": "AAPL,MSFT,GOOG"})
            corr = _extract_payload(corr_raw)
            _assert_common_contract(corr, "get_portfolio_correlation_tool")
            if "error" not in corr:
                _assert("correlation_matrix" in corr, "get_portfolio_correlation_tool: missing correlation_matrix")
                _assert("high_correlation_pairs" in corr, "get_portfolio_correlation_tool: missing high_correlation_pairs")
                _assert(isinstance(corr["correlation_matrix"], dict), "correlation_matrix must be a dict")
                _assert(len(corr["correlation_matrix"]) >= 2, "correlation_matrix should include at least 2 symbols")
                _assert("effective_symbols" in corr, "get_portfolio_correlation_tool: missing effective_symbols")
                _assert("dropped_symbols" in corr, "get_portfolio_correlation_tool: missing dropped_symbols")

            print("Testing get_portfolio_correlation_tool invalid input...")
            corr_invalid_raw = await session.call_tool("get_portfolio_correlation_tool", arguments={"symbols": ""})
            corr_invalid = _extract_payload(corr_invalid_raw)
            _assert_common_contract(corr_invalid, "get_portfolio_correlation_tool_invalid")
            _assert("error" in corr_invalid, "get_portfolio_correlation_tool invalid input should return error")

            print("MCP contract tests passed.")


if __name__ == "__main__":
    try:
        asyncio.run(test_server())
    except ImportError:
        print("Please install the 'mcp' package to run this test:")
        print("pip install mcp")
    except Exception as e:
        print(f"Error: {e}")
