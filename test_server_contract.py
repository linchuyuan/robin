import unittest
from unittest.mock import patch
import tempfile

import server


class TestServerContracts(unittest.TestCase):
    @patch("server.get_economic_events_feed")
    def test_get_economic_events_success(self, mock_feed):
        mock_feed.return_value = {
            "source": "forexfactory_week_feed",
            "events": [
                {
                    "title": "FOMC Meeting Minutes",
                    "country": "USD",
                    "datetime": "2026-02-18T14:00:00-05:00",
                    "impact": "High",
                    "forecast": "",
                    "previous": "",
                }
            ],
        }
        result = server.get_economic_events.fn(limit=5, days_ahead=7, countries="USD")
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("count"), 1)
        self.assertIn("events", result)
        self.assertIn("result_text", result)
        self.assertNotIn("error", result)

    @patch("server.get_economic_events_feed", side_effect=RuntimeError("feed down"))
    def test_get_economic_events_error(self, _mock_feed):
        result = server.get_economic_events.fn()
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("count"), 0)
        self.assertIn("error", result)
        self.assertIn("result_text", result)

    @patch("server.evaluate_pretrade_policy")
    @patch("server.get_session", return_value=None)
    @patch("server.place_order")
    def test_execute_order_rejects_missing_limit_price(self, mock_place_order, _mock_session, mock_policy):
        result = server.execute_order.fn("AAPL", 1, "buy", order_type="limit", price=None)
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        self.assertIn("price is required", result.get("error", ""))
        mock_policy.assert_not_called()
        mock_place_order.assert_not_called()

    @patch("server.evaluate_pretrade_policy")
    @patch("server.get_session", return_value=None)
    @patch("server.place_crypto_order")
    def test_execute_crypto_order_rejects_non_positive_quantity(self, mock_place_crypto_order, _mock_session, mock_policy):
        result = server.execute_crypto_order.fn("BTC", 0, "buy")
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        self.assertIn("quantity must be positive", result.get("error", "").lower())
        mock_policy.assert_not_called()
        mock_place_crypto_order.assert_not_called()

    @patch("server.evaluate_pretrade_policy", return_value={"allowed": True, "reason": "ok", "checks": []})
    @patch("server.get_session", return_value=None)
    @patch("server.place_order")
    def test_execute_order_defaults_to_live_mode(self, mock_place_order, _mock_session, _mock_policy):
        mock_place_order.return_value = {"id": "abc-123", "state": "queued"}
        with patch.dict("os.environ", {}, clear=True):
            result = server.execute_order.fn("AAPL", 1, "buy")
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("success"))
        self.assertFalse(result.get("paper", False))
        self.assertEqual(result.get("order_id"), "abc-123")
        self.assertIn("result_text", result)
        self.assertIn("policy", result)
        mock_place_order.assert_called_once()

    @patch.dict("os.environ", {"ROBIN_MCP_EXECUTION_MODE": "live"}, clear=False)
    @patch("server.evaluate_pretrade_policy", return_value={"allowed": True, "reason": "ok", "checks": []})
    @patch("server.get_session", return_value=None)
    @patch("server.place_order")
    def test_execute_order_live_mode_redacts_raw_details(self, mock_place_order, _mock_session, _mock_policy):
        mock_place_order.return_value = {"id": "abc-123", "state": "queued", "url": "secretish"}
        result = server.execute_order.fn("AAPL", 1, "buy")
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("success"))
        self.assertFalse(result.get("paper", False))
        self.assertEqual(result.get("order_id"), "abc-123")
        self.assertEqual(result.get("details", {}).get("id"), "abc-123")
        self.assertNotIn("url", result.get("details", {}))

    @patch("server.evaluate_pretrade_policy", return_value={"allowed": True, "reason": "ok", "checks": []})
    @patch("server.get_session", return_value=None)
    @patch("server.place_order")
    def test_execute_order_uses_paper_mode_when_explicit(self, mock_place_order, _mock_session, _mock_policy):
        with tempfile.TemporaryDirectory() as tmp:
            paper_file = f"{tmp}/paper-orders.json"
            with patch.dict(
                "os.environ",
                {
                    "ROBIN_MCP_EXECUTION_MODE": "paper",
                    "ROBIN_PAPER_ORDER_FILE": paper_file,
                },
                clear=False,
            ):
                result = server.execute_order.fn("AAPL", 1, "buy", order_type="limit", price=200)

        self.assertTrue(result.get("success"))
        self.assertTrue(result.get("paper"))
        self.assertFalse(result.get("live_trading_enabled"))
        self.assertTrue(str(result.get("order_id", "")).startswith("paper-"))
        mock_place_order.assert_not_called()

    @patch.dict("os.environ", {"ROBIN_MCP_ALLOW_LIVE_TRADING": "1"}, clear=False)
    @patch("server.evaluate_pretrade_policy", return_value={"allowed": True, "reason": "ok", "checks": []})
    @patch("server.get_session", return_value=None)
    @patch("server.place_order")
    def test_execute_order_rejects_error_payload(self, mock_place_order, _mock_session, _mock_policy):
        mock_place_order.return_value = {"detail": "insufficient buying power"}
        result = server.execute_order.fn("AAPL", 1, "buy")
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        self.assertIn("insufficient buying power", result.get("error", ""))
        self.assertIn("result_text", result)

    @patch("server.evaluate_pretrade_policy", return_value={"allowed": False, "reason": "blocked", "checks": []})
    @patch("server.get_session", return_value=None)
    @patch("server.place_order")
    def test_execute_order_blocks_on_policy(self, mock_place_order, _mock_session, _mock_policy):
        result = server.execute_order.fn("AAPL", 1, "buy")
        self.assertFalse(result.get("success"))
        self.assertIn("blocked", result.get("error", ""))
        self.assertIn("policy", result)
        mock_place_order.assert_not_called()

    @patch.dict("os.environ", {"ROBIN_MCP_ALLOW_LIVE_TRADING": "1"}, clear=False)
    @patch("server.get_session", return_value=None)
    @patch("server.rh.cancel_stock_order")
    def test_cancel_order_detects_api_error(self, mock_cancel, _mock_session):
        mock_cancel.return_value = {"detail": "order already filled"}
        result = server.cancel_order.fn("oid-1")
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        self.assertIn("order already filled", result.get("error", ""))
        self.assertIn("details", result)
        self.assertIn("result_text", result)

    @patch.dict("os.environ", {"ROBIN_MCP_ALLOW_LIVE_TRADING": "1"}, clear=False)
    @patch("server.get_session", return_value=None)
    @patch("server.rh.cancel_stock_order")
    def test_cancel_order_accepts_valid_response(self, mock_cancel, _mock_session):
        mock_cancel.return_value = {"id": "oid-1", "state": "cancel_queued"}
        result = server.cancel_order.fn("oid-1")
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("order_id"), "oid-1")
        self.assertIn("result_text", result)

    @patch.dict("os.environ", {"ROBIN_MCP_ALLOW_LIVE_TRADING": "1"}, clear=False)
    @patch("server.evaluate_pretrade_policy", return_value={"allowed": True, "reason": "ok", "checks": []})
    @patch("server.get_session", return_value=None)
    @patch("server.place_crypto_order")
    def test_execute_crypto_order_rejects_missing_id(self, mock_place_crypto_order, _mock_session, _mock_policy):
        mock_place_crypto_order.return_value = {"state": "rejected"}
        result = server.execute_crypto_order.fn("BTC", 0.1, "buy")
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"))
        self.assertIn("missing order id", result.get("error", "").lower())
        self.assertIn("result_text", result)
        self.assertIn("policy", result)

    @patch("server.evaluate_pretrade_policy", return_value={"allowed": False, "reason": "blocked", "checks": []})
    @patch("server.get_session", return_value=None)
    @patch("server.place_crypto_order")
    def test_execute_crypto_order_blocks_on_policy(self, mock_place_crypto_order, _mock_session, _mock_policy):
        result = server.execute_crypto_order.fn("BTC", 0.1, "buy")
        self.assertFalse(result.get("success"))
        self.assertIn("blocked", result.get("error", ""))
        self.assertIn("policy", result)
        mock_place_crypto_order.assert_not_called()

    def test_timestamp_is_utc_and_zulu(self):
        result = server.get_timestamp.fn()
        self.assertIsInstance(result, dict)
        self.assertIn("iso", result)
        self.assertTrue(result["iso"].endswith("Z"))
        self.assertEqual(result.get("timezone"), "UTC")
        self.assertIn("UTC", result.get("result_text", ""))


if __name__ == "__main__":
    unittest.main()
