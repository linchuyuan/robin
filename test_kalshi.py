import unittest
from unittest.mock import patch

from kalshi import (
    get_kalshi_stock_context,
    list_kalshi_markets,
    normalize_market,
    search_kalshi_markets,
)
from mcp_kalshi_tools import register_kalshi_tools


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def sample_markets_payload():
    return {
        "markets": [
            {
                "ticker": "KXFED-26DEC-T4.00",
                "event_ticker": "KXFED-26DEC",
                "series_ticker": "KXFED",
                "title": "Will the Fed funds rate be above 4.00%?",
                "subtitle": "Federal Reserve target rate",
                "status": "active",
                "yes_bid": 44,
                "yes_ask": 47,
                "volume": 1234,
                "open_interest": 99,
                "liquidity": 25000,
            },
            {
                "ticker": "KXNVDA-26DEC",
                "event_ticker": "KXNVDA",
                "series_ticker": "KXSTOCKS",
                "title": "Will Nvidia close above a target price?",
                "subtitle": "NVDA market",
                "status": "active",
                "yes_bid_dollars": "0.61",
                "yes_ask_dollars": "0.64",
                "volume_fp": "200",
            },
        ],
        "cursor": "",
    }


class TestKalshiClient(unittest.TestCase):
    def test_normalize_market_accepts_cent_and_dollar_prices(self):
        market = normalize_market(sample_markets_payload()["markets"][1])

        self.assertEqual(market["ticker"], "KXNVDA-26DEC")
        self.assertEqual(market["yes_bid"], 61)
        self.assertEqual(market["yes_ask"], 64)
        self.assertEqual(market["implied_probability_mid"], 62.5)
        self.assertEqual(market["volume"], 200)

    @patch("kalshi.requests.get")
    def test_list_markets_calls_public_endpoint(self, mock_get):
        mock_get.return_value = FakeResponse(sample_markets_payload())

        result = list_kalshi_markets(status="open", limit=2)

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["markets"][0]["ticker"], "KXFED-26DEC-T4.00")
        args, kwargs = mock_get.call_args
        self.assertTrue(args[0].endswith("/markets"))
        self.assertEqual(kwargs["params"]["status"], "open")

    @patch("kalshi.requests.get")
    def test_search_markets_filters_locally(self, mock_get):
        mock_get.return_value = FakeResponse(sample_markets_payload())

        result = search_kalshi_markets("Nvidia", limit=5)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["markets"][0]["ticker"], "KXNVDA-26DEC")

    @patch("kalshi.search_kalshi_markets")
    def test_stock_context_combines_symbol_and_macro_queries(self, mock_search):
        mock_search.side_effect = [
            {"markets": [normalize_market(sample_markets_payload()["markets"][1])]},
            {"markets": []},
            {"markets": [normalize_market(sample_markets_payload()["markets"][0])]},
        ]

        result = get_kalshi_stock_context("NVDA", company_name="Nvidia", limit=2)

        self.assertEqual(result["symbol"], "NVDA")
        self.assertEqual(result["count"], 2)
        self.assertIn("Nvidia", result["queries"])


class TestKalshiMCPTools(unittest.TestCase):
    @patch("mcp_kalshi_tools.search_kalshi_markets")
    def test_register_market_search_tool(self, mock_search):
        mock_search.return_value = {
            "query": "Fed",
            "status": "open",
            "markets": [normalize_market(sample_markets_payload()["markets"][0])],
            "count": 1,
        }
        mcp = FakeMCP()
        register_kalshi_tools(mcp)

        result = mcp.tools["get_kalshi_markets"](query="Fed")

        self.assertEqual(result["count"], 1)
        self.assertIn("result_text", result)
        self.assertIn("KXFED", result["result_text"])


if __name__ == "__main__":
    unittest.main()
