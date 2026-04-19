"""
Smoke tests for advanced quant / risk / data modules.

These are pure-Python unit tests (no network, no yfinance dependency where
possible) that verify core math, edge-case handling, and contract stability.
Run with: pytest test_advanced_modules.py  (or python -m unittest)
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


class TestExecutionModels(unittest.TestCase):
    def test_slippage_large_cap_tiny_order(self):
        from execution_models import estimate_slippage_bps
        r = estimate_slippage_bps(
            order_notional_usd=1_000, adv_usd=1e10, vol_20d_annual=0.20
        )
        self.assertLess(r["slippage_bps"], 10, "Large-cap tiny order should slip <10 bps")
        self.assertEqual(r["bucket"], "large")

    def test_slippage_small_cap_large_order(self):
        from execution_models import estimate_slippage_bps
        r = estimate_slippage_bps(
            order_notional_usd=100_000, adv_usd=1_000_000, vol_20d_annual=0.50
        )
        self.assertGreater(r["slippage_bps"], 50, "Small-cap ≥10% ADV should slip materially")
        self.assertEqual(r["bucket"], "small")

    def test_slippage_open_close_penalty(self):
        from execution_models import estimate_slippage_bps
        midday = estimate_slippage_bps(
            order_notional_usd=50_000, adv_usd=1e8, vol_20d_annual=0.25, minute_of_day=180
        )["slippage_bps"]
        open_bar = estimate_slippage_bps(
            order_notional_usd=50_000, adv_usd=1e8, vol_20d_annual=0.25, minute_of_day=0
        )["slippage_bps"]
        self.assertGreater(open_bar, midday * 1.5, "Open bar should slip ≥1.5x midday")

    def test_vwap_plan_sums_to_total(self):
        from execution_models import vwap_slice_plan, default_us_equity_volume_profile
        plan = vwap_slice_plan(total_qty=1000, volume_profile_pct=default_us_equity_volume_profile())
        self.assertEqual(sum(s["shares"] for s in plan), 1000)
        self.assertTrue(all(s["fraction"] > 0 for s in plan))


class TestOptionsFlow(unittest.TestCase):
    def test_fit_vol_smile_trivial(self):
        from options_flow import fit_vol_smile
        calls = [
            {"strike": 95, "implied_volatility": 0.35, "open_interest": 1000, "bid": 1.0},
            {"strike": 97, "implied_volatility": 0.32, "open_interest": 1000, "bid": 1.0},
            {"strike": 100, "implied_volatility": 0.30, "open_interest": 1000, "bid": 1.0},
            {"strike": 103, "implied_volatility": 0.31, "open_interest": 1000, "bid": 1.0},
            {"strike": 105, "implied_volatility": 0.34, "open_interest": 1000, "bid": 1.0},
        ]
        result = fit_vol_smile(calls, spot=100.0)
        self.assertTrue(result.get("available"), f"Fit should succeed: {result}")
        self.assertAlmostEqual(result["atm_iv"], 0.30, delta=0.03)
        # V-shape smile has positive curvature
        self.assertGreater(result["smile_curvature"], 0)

    def test_fit_vol_smile_too_few_strikes(self):
        from options_flow import fit_vol_smile
        result = fit_vol_smile([{"strike": 100, "implied_volatility": 0.3, "open_interest": 1000, "bid": 1}], spot=100)
        self.assertFalse(result.get("available"))

    def test_detect_unusual_activity_no_spot(self):
        from options_flow import detect_unusual_activity
        r = detect_unusual_activity({"calls": [], "puts": [], "current_price": 0})
        self.assertFalse(r.get("available"))

    def test_detect_unusual_activity_basic(self):
        from options_flow import detect_unusual_activity
        chain = {
            "symbol": "AAPL", "expiration_date": "2026-05-16", "current_price": 100.0,
            "calls": [
                {"strike": 100, "volume": 1000, "open_interest": 500, "implied_volatility": 0.30, "bid": 2, "ask": 2.1, "delta": 0.50},
                {"strike": 105, "volume": 5000, "open_interest": 800, "implied_volatility": 0.28, "bid": 0.5, "ask": 0.6, "delta": 0.25},
            ],
            "puts": [
                {"strike": 100, "volume": 900, "open_interest": 500, "implied_volatility": 0.31, "bid": 2, "ask": 2.1, "delta": -0.50},
                {"strike": 95, "volume": 800, "open_interest": 700, "implied_volatility": 0.35, "bid": 0.6, "ask": 0.7, "delta": -0.25},
            ],
        }
        r = detect_unusual_activity(chain)
        self.assertTrue(r.get("available"))
        self.assertIsNotNone(r.get("volume_pcr"))
        self.assertIn("signals", r)


class TestDriftMonitor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.drift_path = os.path.join(self.tmp, "drift.json")
        os.environ["ROBIN_DRIFT_FILE"] = self.drift_path
        # Force re-import so module picks up the new env var
        import importlib
        import drift_monitor
        importlib.reload(drift_monitor)
        self.dm = drift_monitor

    def test_record_valid_fill(self):
        r = self.dm.record_live_fill(
            symbol="AAPL", side="buy", quantity=10,
            requested_price=200.0, avg_fill_price=200.20,
            order_notional_usd=2000,
        )
        self.assertTrue(r["recorded"])
        self.assertAlmostEqual(r["record"]["actual_slippage_bps"], 10.0, places=1)

    def test_invalid_prices_rejected(self):
        r = self.dm.record_live_fill(
            symbol="AAPL", side="buy", quantity=10,
            requested_price=0, avg_fill_price=200,
            order_notional_usd=2000,
        )
        self.assertFalse(r["recorded"])

    def test_stats_computation(self):
        for bps in [5, 8, 12, 3, 20]:
            fill_price = 100.0 * (1 + bps / 10_000)
            self.dm.record_live_fill(
                symbol="AAPL", side="buy", quantity=1,
                requested_price=100.0, avg_fill_price=fill_price,
                order_notional_usd=100,
            )
        report = self.dm.get_drift_report()
        self.assertGreaterEqual(report["fill_count"], 5)
        self.assertGreater(report["stats"]["mean_actual_slippage_bps"], 0)

    def tearDown(self):
        try:
            os.unlink(self.drift_path)
        except FileNotFoundError:
            pass
        os.environ.pop("ROBIN_DRIFT_FILE", None)


class TestInsiderFlow(unittest.TestCase):
    def test_score_empty(self):
        from insider_flow import score_insider_signal
        s = score_insider_signal([])
        self.assertEqual(s["tier"], "no_signal")
        self.assertEqual(s["catalyst_points_bonus"], 0)

    def test_score_cluster_buy(self):
        from insider_flow import score_insider_signal
        txns = [
            {"transaction_type": "P", "insider_title": "CEO", "value_usd": 300_000, "insider_name": "A"},
            {"transaction_type": "P", "insider_title": "CFO", "value_usd": 250_000, "insider_name": "B"},
            {"transaction_type": "P", "insider_title": "Director", "value_usd": 150_000, "insider_name": "C"},
        ]
        s = score_insider_signal(txns)
        self.assertEqual(s["tier"], "cluster_buy")
        self.assertEqual(s["catalyst_points_bonus"], 5)
        self.assertEqual(s["unique_insider_buyers"], 3)

    def test_score_filters_small_and_non_exec(self):
        from insider_flow import score_insider_signal
        txns = [
            {"transaction_type": "P", "insider_title": "Advisor", "value_usd": 500_000, "insider_name": "X"},
            {"transaction_type": "P", "insider_title": "CEO", "value_usd": 50_000, "insider_name": "Y"},
        ]
        s = score_insider_signal(txns)
        self.assertEqual(s["tier"], "no_signal", "Should filter non-exec title and <100k")


class TestEarningsConsensus(unittest.TestCase):
    def test_surprise_prob_no_inputs(self):
        from earnings_consensus import compute_surprise_probability
        consensus = {"available": True}
        r = compute_surprise_probability(consensus)
        self.assertEqual(r["surprise_probability"], 0.5)
        self.assertEqual(r["confidence"], "low")

    def test_surprise_prob_strong_positive(self):
        from earnings_consensus import compute_surprise_probability
        consensus = {
            "available": True,
            "eps_revision_30d_pct": 0.03,
            "eps_revision_7d_pct": 0.015,
            "guidance_hint": "above_consensus",
            "beat_rate_last_4q": 0.75,
            "eps_dispersion_pct": 0.10,
        }
        r = compute_surprise_probability(consensus)
        self.assertGreaterEqual(r["surprise_probability"], 0.70)
        self.assertEqual(r["confidence"], "high")

    def test_surprise_prob_clamped(self):
        from earnings_consensus import compute_surprise_probability
        # Try to push probability above 0.9
        consensus = {
            "available": True,
            "eps_revision_30d_pct": 1.0, "eps_revision_7d_pct": 1.0,
            "guidance_hint": "above_consensus", "beat_rate_last_4q": 1.0,
            "eps_dispersion_pct": 0.05,
        }
        r = compute_surprise_probability(consensus)
        self.assertLessEqual(r["surprise_probability"], 0.90)
        self.assertGreaterEqual(r["surprise_probability"], 0.10)


class TestStressTester(unittest.TestCase):
    def test_replay_unknown_shock(self):
        from stress_tester import replay_shock
        r = replay_shock([{"symbol": "AAPL", "market_value_usd": 1000}], "made_up_shock")
        self.assertFalse(r.get("available"))
        self.assertIn("known_shocks", r)

    def test_replay_empty_portfolio(self):
        from stress_tester import replay_shock
        r = replay_shock([], "covid_2020_03")
        self.assertFalse(r.get("available"))

    def test_tail_multiplier_applied_only_to_losses(self):
        from stress_tester import replay_shock
        # Construct a portfolio with 100% SPY; expected move = -0.32 in covid shock
        r = replay_shock([{"symbol": "SPY", "market_value_usd": 10_000}], "covid_2020_03", apply_tail_multiplier=True)
        self.assertTrue(r["available"])
        self.assertAlmostEqual(r["linear_pnl_pct"], -0.32, places=2)
        # With 1.5x multiplier on losses
        self.assertAlmostEqual(r["expected_pnl_pct"], -0.48, places=2)

    def test_tail_multiplier_off(self):
        from stress_tester import replay_shock
        r = replay_shock([{"symbol": "SPY", "market_value_usd": 10_000}], "covid_2020_03", apply_tail_multiplier=False)
        self.assertAlmostEqual(r["expected_pnl_pct"], r["linear_pnl_pct"], places=4)


class TestQuantAdvanced(unittest.TestCase):
    def test_kelly_sizing_basic(self):
        from quant_advanced import kelly_sizing
        r = kelly_sizing(win_rate=0.60, avg_win_pct=0.10, avg_loss_pct=0.05)
        self.assertTrue(r["available"])
        self.assertGreater(r["suggested_position_pct"], 0)

    def test_kelly_invalid(self):
        from quant_advanced import kelly_sizing
        r = kelly_sizing(win_rate=0.5, avg_win_pct=0, avg_loss_pct=0.05)
        self.assertFalse(r["available"])

    def test_kelly_quarter_default(self):
        from quant_advanced import kelly_sizing
        r = kelly_sizing(win_rate=0.6, avg_win_pct=0.1, avg_loss_pct=0.05)
        # Quarter Kelly of ~0.20 full Kelly is ~0.05
        self.assertLess(r["suggested_position_pct"], 10)


class TestNewsSentiment(unittest.TestCase):
    def test_score_text_empty(self):
        from news_sentiment import _score_text
        p, pos, neg = _score_text("")
        self.assertEqual(p, 0.0)

    def test_score_text_positive(self):
        from news_sentiment import _score_text
        p, pos, neg = _score_text("Company beat earnings, raised guidance, strong quarter")
        self.assertGreater(p, 0)

    def test_score_text_negative(self):
        from news_sentiment import _score_text
        p, pos, neg = _score_text("Company missed earnings, layoffs announced, weakness")
        self.assertLess(p, 0)

    def test_combine_sources_weighted(self):
        from news_sentiment import combine_sentiment_sources
        r = combine_sentiment_sources(reddit_score=0.5, reddit_confidence=0.3, news_score=-0.2, news_weighted_count=5)
        self.assertIn("combined_score", r)
        self.assertEqual(len(r["sources"]), 2)


if __name__ == "__main__":
    unittest.main()
