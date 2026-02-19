import unittest
from unittest.mock import patch
import sys
import types

if "robin_stocks" not in sys.modules:
    robin_stocks_pkg = types.ModuleType("robin_stocks")
    robinhood_mod = types.ModuleType("robin_stocks.robinhood")
    robinhood_mod.get_all_open_stock_orders = lambda: []
    robinhood_mod.get_symbol_by_url = lambda _url: None
    robinhood_mod.get_quotes = lambda _symbol: []
    robinhood_mod.load_account_profile = lambda: {}
    robinhood_mod.load_portfolio_profile = lambda: {}
    robinhood_mod.build_holdings = lambda: {}
    robin_stocks_pkg.robinhood = robinhood_mod
    sys.modules["robin_stocks"] = robin_stocks_pkg
    sys.modules["robin_stocks.robinhood"] = robinhood_mod

if "account" not in sys.modules:
    account_mod = types.ModuleType("account")
    account_mod.get_account_profile = lambda: {}
    sys.modules["account"] = account_mod

if "portfolio" not in sys.modules:
    portfolio_mod = types.ModuleType("portfolio")
    portfolio_mod.list_positions = lambda: []
    sys.modules["portfolio"] = portfolio_mod

if "market_calendar" not in sys.modules:
    market_calendar_mod = types.ModuleType("market_calendar")
    market_calendar_mod.get_market_status = lambda: {"session": "unknown"}
    sys.modules["market_calendar"] = market_calendar_mod

if "reddit_sentiment" not in sys.modules:
    reddit_sentiment_mod = types.ModuleType("reddit_sentiment")
    reddit_sentiment_mod.get_reddit_sentiment_snapshot = lambda **_kwargs: {"symbols": []}
    sys.modules["reddit_sentiment"] = reddit_sentiment_mod

from pretrade_policy import evaluate_pretrade_policy


class TestPretradePolicy(unittest.TestCase):
    @patch.dict("os.environ", {"ROBIN_ENABLE_SENTIMENT_GUARDRAIL": "0"}, clear=False)
    @patch("pretrade_policy.get_market_status", return_value={"session": "regular"})
    @patch("pretrade_policy.rh.get_all_open_stock_orders", return_value=[])
    @patch("pretrade_policy.list_positions", return_value=[])
    @patch("pretrade_policy.get_account_profile", return_value={})
    @patch("pretrade_policy._first_quote_price", return_value=10.0)
    def test_buy_blocks_when_account_data_unavailable(
        self,
        _mock_quote,
        _mock_account,
        _mock_positions,
        _mock_orders,
        _mock_market,
    ):
        result = evaluate_pretrade_policy(
            symbol="AAPL",
            qty=1,
            side="buy",
            order_type="market",
            price=None,
            extended_hours=False,
        )
        self.assertFalse(result.get("allowed"))
        self.assertEqual(result.get("blocked_by"), "account_data_required")

    @patch.dict("os.environ", {"ROBIN_ENABLE_SENTIMENT_GUARDRAIL": "0"}, clear=False)
    @patch("pretrade_policy.get_market_status", return_value={"session": "regular"})
    @patch(
        "pretrade_policy.rh.get_all_open_stock_orders",
        return_value=[{"symbol": "AAPL", "side": "buy", "quantity": "4", "price": "20"}],
    )
    @patch("pretrade_policy.list_positions", return_value=[])
    @patch(
        "pretrade_policy.get_account_profile",
        return_value={
            "equity": 1000.0,
            "equity_previous_close": 1000.0,
            "buying_power": 100.0,
            "market_value": 0.0,
        },
    )
    @patch("pretrade_policy._first_quote_price", return_value=20.0)
    def test_buying_power_accounts_for_pending_buy_notional(
        self,
        _mock_quote,
        _mock_account,
        _mock_positions,
        _mock_orders,
        _mock_market,
    ):
        result = evaluate_pretrade_policy(
            symbol="MSFT",
            qty=2,
            side="buy",
            order_type="limit",
            price=20.0,
            extended_hours=False,
        )
        self.assertFalse(result.get("allowed"))
        self.assertEqual(result.get("blocked_by"), "buying_power")
        checks = result.get("checks", [])
        buying_power_check = next((item for item in checks if item.get("name") == "buying_power"), {})
        self.assertIn("pending_buy_notional_total=80.00", buying_power_check.get("detail", ""))

    @patch.dict("os.environ", {"ROBIN_ENABLE_SENTIMENT_GUARDRAIL": "0"}, clear=False)
    @patch("pretrade_policy.get_market_status", return_value={"session": "regular"})
    @patch("pretrade_policy.rh.get_all_open_stock_orders", return_value=[])
    @patch("pretrade_policy.list_positions", return_value=[])
    @patch(
        "pretrade_policy.get_account_profile",
        return_value={
            "equity": 1000.0,
            "equity_previous_close": 1000.0,
            "buying_power": 1000.0,
            "market_value": 0.0,
        },
    )
    @patch("pretrade_policy._first_quote_price", return_value=10.0)
    def test_hard_exclude_blocks_sell_orders(
        self,
        _mock_quote,
        _mock_account,
        _mock_positions,
        _mock_orders,
        _mock_market,
    ):
        result = evaluate_pretrade_policy(
            symbol="CEG",
            qty=1,
            side="sell",
            order_type="market",
            price=None,
            extended_hours=False,
        )
        self.assertFalse(result.get("allowed"))
        self.assertEqual(result.get("blocked_by"), "hard_exclude_list")
        checks = result.get("checks", [])
        hard_exclude_check = next((item for item in checks if item.get("name") == "hard_exclude_list"), {})
        self.assertEqual(hard_exclude_check.get("status"), "fail")
        metrics = result.get("metrics", {})
        self.assertTrue(metrics.get("hard_exclude_hit"))

    @patch.dict("os.environ", {"ROBIN_ENABLE_SENTIMENT_GUARDRAIL": "0"}, clear=False)
    @patch("pretrade_policy.get_market_status", return_value={"session": "regular"})
    @patch("pretrade_policy.rh.get_all_open_stock_orders", return_value=[])
    @patch("pretrade_policy.list_positions", return_value=[{"symbol": "AAPL", "intraday_profit_loss": -5.0, "equity": 200.0}])
    @patch(
        "pretrade_policy.get_account_profile",
        return_value={
            "equity": 1000.0,
            "equity_previous_close": 1100.0,
            "buying_power": 2000.0,
            "market_value": 300.0,
        },
    )
    @patch("pretrade_policy._first_quote_price", return_value=10.0)
    def test_daily_loss_gate_uses_equity_previous_close(
        self,
        _mock_quote,
        _mock_account,
        _mock_positions,
        _mock_orders,
        _mock_market,
    ):
        result = evaluate_pretrade_policy(
            symbol="AAPL",
            qty=1,
            side="buy",
            order_type="market",
            price=None,
            extended_hours=False,
        )
        self.assertFalse(result.get("allowed"))
        self.assertEqual(result.get("blocked_by"), "daily_loss_limit")
        checks = result.get("checks", [])
        daily_loss_check = next((item for item in checks if item.get("name") == "daily_loss_limit"), {})
        self.assertEqual(daily_loss_check.get("status"), "fail")
        self.assertIn("source=equity_vs_previous_close", daily_loss_check.get("detail", ""))
        metrics = result.get("metrics", {})
        self.assertEqual(metrics.get("daily_pnl_source"), "equity_vs_previous_close")
        self.assertAlmostEqual(float(metrics.get("daily_pnl_total")), -100.0, places=4)

    @patch.dict(
        "os.environ",
        {
            "ROBIN_ENABLE_SENTIMENT_GUARDRAIL": "1",
            "ROBIN_SENTIMENT_FAIL_CLOSED": "1",
        },
        clear=False,
    )
    @patch("pretrade_policy.get_reddit_sentiment_snapshot", side_effect=RuntimeError("reddit unavailable"))
    @patch("pretrade_policy.get_market_status", return_value={"session": "regular"})
    @patch("pretrade_policy.rh.get_all_open_stock_orders", return_value=[])
    @patch("pretrade_policy.list_positions", return_value=[])
    @patch(
        "pretrade_policy.get_account_profile",
        return_value={
            "equity": 1000.0,
            "equity_previous_close": 1000.0,
            "buying_power": 2000.0,
            "market_value": 0.0,
        },
    )
    @patch("pretrade_policy._first_quote_price", return_value=10.0)
    def test_sentiment_fail_closed_blocks_on_unavailable_snapshot(
        self,
        _mock_quote,
        _mock_account,
        _mock_positions,
        _mock_orders,
        _mock_market,
        _mock_sentiment,
    ):
        result = evaluate_pretrade_policy(
            symbol="AAPL",
            qty=1,
            side="buy",
            order_type="market",
            price=None,
            extended_hours=False,
        )
        self.assertFalse(result.get("allowed"))
        self.assertEqual(result.get("blocked_by"), "sentiment_guardrail")
        checks = result.get("checks", [])
        sentiment_check = next((item for item in checks if item.get("name") == "sentiment_guardrail"), {})
        self.assertEqual(sentiment_check.get("status"), "fail")
        self.assertIn("fail_closed=1", sentiment_check.get("detail", ""))

    @patch.dict(
        "os.environ",
        {
            "ROBIN_ENABLE_SENTIMENT_GUARDRAIL": "1",
            "ROBIN_SENTIMENT_FAIL_CLOSED": "0",
        },
        clear=False,
    )
    @patch("pretrade_policy.get_reddit_sentiment_snapshot", side_effect=RuntimeError("reddit unavailable"))
    @patch("pretrade_policy.get_market_status", return_value={"session": "regular"})
    @patch("pretrade_policy.rh.get_all_open_stock_orders", return_value=[])
    @patch("pretrade_policy.list_positions", return_value=[])
    @patch(
        "pretrade_policy.get_account_profile",
        return_value={
            "equity": 1000.0,
            "equity_previous_close": 1000.0,
            "buying_power": 2000.0,
            "market_value": 0.0,
        },
    )
    @patch("pretrade_policy._first_quote_price", return_value=10.0)
    def test_sentiment_fail_open_allows_when_configured(
        self,
        _mock_quote,
        _mock_account,
        _mock_positions,
        _mock_orders,
        _mock_market,
        _mock_sentiment,
    ):
        result = evaluate_pretrade_policy(
            symbol="AAPL",
            qty=1,
            side="buy",
            order_type="market",
            price=None,
            extended_hours=False,
        )
        self.assertTrue(result.get("allowed"))
        checks = result.get("checks", [])
        sentiment_check = next((item for item in checks if item.get("name") == "sentiment_guardrail"), {})
        self.assertEqual(sentiment_check.get("status"), "pass")
        self.assertIn("fail_closed=0", sentiment_check.get("detail", ""))


if __name__ == "__main__":
    unittest.main()
