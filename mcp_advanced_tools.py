"""MCP registrations for advanced quant / risk / data tools.

Exposes:
  - get_macro_regime_dashboard
  - get_sector_breadth_tool
  - get_news_sentiment_tool
  - get_insider_flow_tool
  - get_unusual_options_activity_tool
  - get_earnings_surprise_tool
  - get_factor_attribution_tool
  - get_portfolio_risk_summary_tool (VaR / CVaR / risk attribution)
  - get_portfolio_optimization_tool (mean-variance + risk parity + Kelly)
  - get_stress_test_tool
  - record_live_fill_tool
  - get_drift_report_tool
  - get_slippage_estimate_tool
  - backtest_params_vs_trace_tool (daily-review auto-backtest)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from macro_data import get_regime_dashboard, get_sector_breadth
from news_sentiment import get_news_sentiment, combine_sentiment_sources
from insider_flow import get_insider_flow
from options_flow import detect_unusual_activity
from earnings_consensus import get_earnings_signal
from quant_advanced import (
    compute_factor_attribution,
    compute_var_cvar,
    kelly_sizing,
    risk_parity_weights,
    mean_variance_weights,
    position_risk_attribution,
)
from stress_tester import replay_shock, replay_all_shocks, SHOCK_CATALOG
from drift_monitor import record_live_fill, get_drift_report
from execution_models import estimate_slippage_bps


def register_advanced_tools(mcp) -> None:

    @mcp.tool()
    def get_macro_regime_dashboard() -> dict:
        """
        Composite macro regime snapshot: yield-curve proxy (TLT/SHY), credit spread
        (HYG/LQD), VIX term structure, flight-to-quality. Returns a single regime
        bucket + confidence for downstream agents.
        """
        result = get_regime_dashboard()
        text = (
            f"Regime: {result.get('regime')} (confidence {result.get('confidence')})"
        )
        return {**result, "result_text": text}

    @mcp.tool()
    def get_sector_breadth_tool() -> dict:
        """
        Fraction of 11 sector ETFs positive over 5/20 day windows plus
        healthy/weak/neutral state for breadth-aware regime gates.
        """
        b = get_sector_breadth()
        text = (
            f"Breadth: {b.get('pct_positive_5d'):.2f} over 5d ({b.get('state')})"
        )
        return {**b, "result_text": text}

    @mcp.tool()
    def get_news_sentiment_tool(symbol: str, lookback_hours: int = 72) -> dict:
        """
        Publisher-tier-weighted, time-decayed news sentiment for a symbol.
        Range [-1, 1]. Combine with Reddit via combine_sentiment_sources.
        """
        out = get_news_sentiment(symbol, lookback_hours)
        text = (
            f"{symbol}: news sentiment {out.get('sentiment_score'):+.2f} from "
            f"{out.get('article_count')} articles (weighted {out.get('weighted_article_count')})"
        )
        return {**out, "result_text": text}

    @mcp.tool()
    def get_insider_flow_tool(symbol: str, days: int = 30) -> dict:
        """
        SEC Form 4 insider transactions for a symbol (openinsider-backed).
        Returns tier (cluster_buy / exec_conviction / small_buy / no_signal) and
        catalyst points bonus per the insider-flow skill rules.
        """
        result = get_insider_flow(symbol, days)
        sig = result.get("signal") or {}
        text = (
            f"{symbol} insider ({days}d): tier={sig.get('tier')}, "
            f"buy_usd={sig.get('net_insider_buy_usd'):.0f}, "
            f"unique_buyers={sig.get('unique_insider_buyers')}, "
            f"bonus_pts={sig.get('catalyst_points_bonus')}"
        )
        return {**result, "result_text": text}

    @mcp.tool()
    def get_unusual_options_activity_tool(symbol: str, expiration_date: str) -> dict:
        """
        Classify unusual options activity on a specific chain:
        V/OI anomalies, pin clusters, smile fit, RR25, signal tier.
        Requires an expiration date; pair with get_yf_option_expirations first.
        """
        from yahoo_finance import get_yf_options
        try:
            chain = get_yf_options(symbol, expiration_date)
        except Exception as e:
            return {"available": False, "error": str(e)}
        # Normalize Yahoo chain to options_flow.detect_unusual_activity's expected keys.
        norm_calls = []
        norm_puts = []
        for opt in chain.get("calls", []):
            norm_calls.append({
                "strike": float(opt.get("strike") or 0),
                "volume": int(opt.get("volume") or 0),
                "open_interest": int(opt.get("openInterest") or 0),
                "implied_volatility": float(opt.get("impliedVolatility") or 0),
                "bid": float(opt.get("bid") or 0),
                "ask": float(opt.get("ask") or 0),
                "delta": opt.get("delta"),
            })
        for opt in chain.get("puts", []):
            norm_puts.append({
                "strike": float(opt.get("strike") or 0),
                "volume": int(opt.get("volume") or 0),
                "open_interest": int(opt.get("openInterest") or 0),
                "implied_volatility": float(opt.get("impliedVolatility") or 0),
                "bid": float(opt.get("bid") or 0),
                "ask": float(opt.get("ask") or 0),
                "delta": opt.get("delta"),
            })
        enriched = {
            "symbol": symbol.upper(),
            "expiration_date": expiration_date,
            "current_price": float(chain.get("current_price") or 0),
            "calls": norm_calls,
            "puts": norm_puts,
        }
        result = detect_unusual_activity(enriched)
        signals = result.get("signals") or []
        text = (
            f"{symbol} {expiration_date}: "
            f"pcr_vol={result.get('volume_pcr')}, rr25={result.get('rr25_vol_points')}, "
            f"signals={', '.join(s.get('type') for s in signals)}"
        )
        return {**result, "result_text": text}

    @mcp.tool()
    def get_earnings_surprise_tool(symbol: str) -> dict:
        """
        Earnings consensus, EPS dispersion, revisions, beat-history,
        and a surprise probability in [0.10, 0.90] for the next earnings print.
        """
        result = get_earnings_signal(symbol)
        consensus = result.get("consensus") or {}
        surprise = result.get("surprise") or {}
        text = (
            f"{symbol} earnings: eps={consensus.get('consensus_eps')}, "
            f"dispersion={consensus.get('eps_dispersion_pct')}, "
            f"surprise_p={surprise.get('surprise_probability')} "
            f"({surprise.get('confidence')})"
        )
        return {**result, "result_text": text}

    @mcp.tool()
    def get_factor_attribution_tool(symbol: str, period: str = "1y") -> dict:
        """
        Fama-French-style factor attribution (MKT / SMB / HML / QMJ / MOM)
        using free tradable ETF proxies. Returns factor betas, alpha, R^2.
        """
        result = compute_factor_attribution(symbol, period)
        if not result.get("available"):
            return {**result, "result_text": f"Attribution unavailable: {result.get('reason')}"}
        betas = result.get("factor_betas") or {}
        text = (
            f"{symbol} factor betas: " + ", ".join(f"{k}={v}" for k, v in betas.items())
            + f" | alpha_annual={result.get('alpha_annual_pct')}% | R^2={result.get('r_squared')}"
        )
        return {**result, "result_text": text}

    @mcp.tool()
    def get_portfolio_risk_summary_tool(confidence: float = 0.95, horizon_days: int = 1) -> dict:
        """
        Combined portfolio risk summary: VaR, CVaR, and per-position risk contribution.
        Pulls current holdings from portfolio.list_positions(). Concentration
        flag fires when a single position drives > 40% of portfolio variance.
        """
        from portfolio import list_positions
        try:
            positions = list_positions() or []
        except Exception as e:
            return {"available": False, "error": str(e)}
        if not positions:
            return {"available": False, "reason": "no_positions", "result_text": "No positions to assess."}
        normalized = [
            {"symbol": p["symbol"], "market_value_usd": float(p.get("equity") or 0)}
            for p in positions
        ]
        var = compute_var_cvar(normalized, confidence=confidence, horizon_days=horizon_days)
        attrib = position_risk_attribution(normalized)
        text_parts = []
        if var.get("available"):
            text_parts.append(
                f"VaR({int(confidence*100)}%, {horizon_days}d): {var.get('var_pct')}% (${var.get('var_usd')}); "
                f"CVaR: {var.get('cvar_pct')}% (${var.get('cvar_usd')})"
            )
        if attrib.get("available") and attrib.get("concentration_flag"):
            text_parts.append(f"CONCENTRATION: {attrib['concentration_flag']}")
        return {
            "available": True,
            "var": var,
            "risk_attribution": attrib,
            "result_text": " | ".join(text_parts) if text_parts else "Risk summary computed.",
        }

    @mcp.tool()
    def get_portfolio_optimization_tool(
        symbols: str,
        method: str = "mean_variance",
        risk_aversion: float = 3.0,
        win_rate: float = 0.0,
        avg_win_pct: float = 0.0,
        avg_loss_pct: float = 0.0,
    ) -> dict:
        """
        Portfolio optimization helper. method in {mean_variance, risk_parity, kelly}.

        - mean_variance: long-only MV weights given risk_aversion.
        - risk_parity: inverse-vol weights.
        - kelly: single-bet Kelly sizing from win_rate / avg_win / avg_loss
          (symbols unused for kelly). Returns fractional (0.25x) by default.
        """
        sym_list = [s.strip().upper() for s in (symbols or "").split(",") if s.strip()]

        if method == "kelly":
            return kelly_sizing(win_rate, avg_win_pct, avg_loss_pct)
        if not sym_list:
            return {"available": False, "reason": "symbols_required_for_that_method"}
        if method == "risk_parity":
            return risk_parity_weights(sym_list)
        return mean_variance_weights(sym_list, risk_aversion)

    @mcp.tool()
    def get_stress_test_tool(scenario: str = "all") -> dict:
        """
        Replay historical (and hypothetical) shock scenarios against current
        portfolio. scenario="all" runs the full catalog; otherwise pass one of:
        covid_2020_03, volmageddon_2018_02, rate_shock_2022, banking_2023_03,
        gfc_2008_09, inflation_surprise_hypo, ai_bubble_unwind_hypo.
        """
        from portfolio import list_positions
        positions = list_positions() or []
        if not positions:
            return {"available": False, "reason": "no_positions"}
        normalized = [
            {"symbol": p["symbol"], "market_value_usd": float(p.get("equity") or 0)}
            for p in positions
        ]
        if scenario == "all":
            result = replay_all_shocks(normalized)
        else:
            result = replay_shock(normalized, scenario)
        return result

    @mcp.tool()
    def get_slippage_estimate_tool(
        order_notional_usd: float,
        adv_usd: float,
        vol_20d_annual: float,
        minute_of_day: int = 195,
    ) -> dict:
        """
        Estimate expected one-way slippage in basis points for a market-style
        fill. Used by portfolio-agent to decide whether expected edge is
        larger than execution cost.
        """
        result = estimate_slippage_bps(
            order_notional_usd=order_notional_usd,
            adv_usd=adv_usd,
            vol_20d_annual=vol_20d_annual,
            minute_of_day=minute_of_day,
        )
        return {**result, "result_text": f"Expected slippage: {result['slippage_bps']} bps"}

    @mcp.tool()
    def record_live_fill_tool(
        symbol: str,
        side: str,
        quantity: float,
        requested_price: float,
        avg_fill_price: float,
        order_notional_usd: float,
        adv_usd_estimate: float = 0.0,
        vol_20d_annual: float = 0.25,
        minute_of_day: int = 195,
        order_type: str = "market",
    ) -> dict:
        """
        Log a live order fill and compute drift vs slippage model.
        Portfolio-agent should call this after each confirmed fill.
        """
        return record_live_fill(
            symbol=symbol, side=side, quantity=quantity,
            requested_price=requested_price, avg_fill_price=avg_fill_price,
            order_notional_usd=order_notional_usd,
            adv_usd_estimate=adv_usd_estimate or None,
            vol_20d_annual=vol_20d_annual or None,
            minute_of_day=minute_of_day,
            order_type=order_type,
        )

    @mcp.tool()
    def get_drift_report_tool() -> dict:
        """Return live-vs-backtest slippage drift summary for calibration tuning."""
        return get_drift_report()

    @mcp.tool()
    def backtest_params_vs_trace_tool(
        champion_path: str = "memory/portfolio-agent-params.json",
        candidate_path: str = "memory/learning-candidate.json",
        trace_dir: str = "memory/decision-trace",
        days: int = 30,
    ) -> dict:
        """
        Replay the last N days of decision traces against champion vs candidate
        parameters. Lightweight replay (not full market simulation) — compares
        what actions the two parameter sets would have produced given the
        same signals recorded in the trace.

        Returns divergence rate and a qualitative alpha-delta estimate.
        """
        champion = _read_json(champion_path)
        candidate = _read_json(candidate_path)
        if not champion or not candidate:
            return {"available": False, "reason": "params_files_missing_or_empty"}

        # Collect traces
        traces_dir = Path(trace_dir)
        if not traces_dir.exists():
            return {"available": False, "reason": f"no_trace_dir: {trace_dir}"}

        cutoff = datetime.now(timezone.utc).date().toordinal() - max(1, int(days))
        relevant = []
        for f in sorted(traces_dir.glob("*.json")):
            stem = f.stem
            try:
                parts = [int(x) for x in stem.split("-")]
                date_ord = datetime(*parts).date().toordinal()
            except Exception:
                continue
            if date_ord < cutoff:
                continue
            try:
                relevant.append(json.loads(f.read_text()))
            except Exception:
                continue

        if not relevant:
            return {"available": False, "reason": "no_trace_files_in_window"}

        # Heuristic replay: compare score_threshold and sizing between the two
        champ_thresh = champion.get("score_threshold", 70)
        cand_thresh = candidate.get("score_threshold", champ_thresh)
        champ_max_pos = champion.get("max_position_pct", 0.15)
        cand_max_pos = candidate.get("max_position_pct", champ_max_pos)

        divergences = 0
        total_decisions = 0
        estimated_alpha_bps = 0.0

        for trace in relevant:
            # Each trace may have a list of decisions or a single action
            decisions = trace.get("decisions") or [trace]
            for d in decisions:
                candidate_score = d.get("score") or d.get("candidate_score")
                if candidate_score is None:
                    continue
                total_decisions += 1
                champ_action = "buy" if candidate_score >= champ_thresh else "skip"
                cand_action = "buy" if candidate_score >= cand_thresh else "skip"
                if champ_action != cand_action:
                    divergences += 1
                    # Crude alpha estimate: use forward d5_return if backfilled
                    d5 = (d.get("outcomes") or {}).get("d5_return")
                    if d5 is not None:
                        # If candidate bought and it was a win, candidate +; if loss, -
                        direction = 1 if cand_action == "buy" else -1
                        estimated_alpha_bps += direction * float(d5) * 10_000

        divergence_rate = divergences / total_decisions if total_decisions else 0.0

        recommendation = "insufficient_data"
        if total_decisions >= 10:
            if estimated_alpha_bps > 50 and divergence_rate < 0.5:
                recommendation = "promote_candidate_to_shadow"
            elif estimated_alpha_bps < -50:
                recommendation = "reject_candidate_worse_than_champion"
            else:
                recommendation = "inconclusive_keep_shadowing"

        return {
            "available": True,
            "decisions_evaluated": total_decisions,
            "divergence_count": divergences,
            "divergence_rate": round(divergence_rate, 3),
            "estimated_alpha_bps_candidate_vs_champion": round(estimated_alpha_bps, 2),
            "recommendation": recommendation,
            "champion_score_threshold": champ_thresh,
            "candidate_score_threshold": cand_thresh,
        }


def _read_json(path: str) -> dict | None:
    try:
        p = Path(path)
        if not p.exists():
            return None
        return json.loads(p.read_text())
    except Exception:
        return None
