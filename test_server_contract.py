import unittest
from unittest.mock import patch

import server


class TestServerContracts(unittest.TestCase):
    @patch("server.evaluate_pretrade_policy", return_value={"allowed": True, "reason": "ok", "checks": []})
    @patch("server.get_session", return_value=None)
    @patch("server.place_order")
    def test_execute_order_success_requires_order_id(self, mock_place_order, _mock_session, _mock_policy):
        mock_place_order.return_value = {"id": "abc-123", "state": "queued"}
        result = server.execute_order.fn("AAPL", 1, "buy")
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("order_id"), "abc-123")
        self.assertIn("result_text", result)
        self.assertIn("policy", result)

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

    @patch("server.get_session", return_value=None)
    @patch("server.rh.cancel_stock_order")
    def test_cancel_order_accepts_valid_response(self, mock_cancel, _mock_session):
        mock_cancel.return_value = {"id": "oid-1", "state": "cancel_queued"}
        result = server.cancel_order.fn("oid-1")
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("order_id"), "oid-1")
        self.assertIn("result_text", result)

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
