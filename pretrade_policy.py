"""Pre-trade policy checks for MCP order execution."""
from __future__ import annotations

import os
from typing import Any

import robin_stocks.robinhood as rh

from account import get_account_profile
from market_calendar import get_market_status
from portfolio import list_positions
from reddit_sentiment import get_reddit_sentiment_snapshot


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _get_float_env(name: str, default: float) -> float:
    return _to_float(os.getenv(name), default)


def _get_int_env(name: str, default: int) -> int:
    try:
        value = os.getenv(name)
        if value in ("", None):
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _is_truthy_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw in ("", None):
        return bool(default)
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _first_quote_price(symbol: str) -> float:
    try:
        quotes = rh.get_quotes(symbol.upper()) or []
        if quotes and isinstance(quotes[0], dict):
            quote = quotes[0]
            for field in ("last_trade_price", "ask_price", "bid_price", "previous_close"):
                price = _to_float(quote.get(field), 0.0)
                if price > 0:
                    return price
    except Exception:
        return 0.0
    return 0.0


def evaluate_pretrade_policy(
    *,
    symbol: str,
    qty: float,
    side: str,
    order_type: str,
    price: float | None,
    extended_hours: bool,
    asset_class: str = "stock",
) -> dict:
    """
    Evaluate policy gates before order submission.

    Returns:
        {
          "allowed": bool,
          "blocked_by": str | None,
          "checks": [{name,status,detail}],
          "metrics": {...},
          "reason": str
        }
    """
    symbol_up = str(symbol).upper().strip()
    side_lc = str(side).lower().strip()
    asset_class_lc = str(asset_class or "stock").lower().strip()
    if asset_class_lc not in {"stock", "crypto"}:
        asset_class_lc = "stock"

    max_daily_loss_pct = _get_float_env("ROBIN_MAX_DAILY_LOSS_PCT", 0.03)
    max_order_notional_pct = _get_float_env("ROBIN_MAX_ORDER_NOTIONAL_PCT", 0.15)
    max_symbol_exposure_pct = _get_float_env("ROBIN_MAX_SYMBOL_EXPOSURE_PCT", 0.30)
    max_pending_orders_per_symbol = _get_int_env("ROBIN_MAX_PENDING_ORDERS_PER_SYMBOL", 3)
    enable_sentiment_guardrail = _is_truthy_env("ROBIN_ENABLE_SENTIMENT_GUARDRAIL", True)
    sentiment_fail_closed = _is_truthy_env("ROBIN_SENTIMENT_FAIL_CLOSED", True)
    sentiment_confidence_floor = _get_float_env("ROBIN_SENTIMENT_CONFIDENCE_FLOOR", 0.45)

    checks: list[dict[str, str]] = []
    blocked_by: str | None = None

    def add_check(name: str, passed: bool, detail: str) -> None:
        nonlocal blocked_by
        checks.append({"name": name, "status": "pass" if passed else "fail", "detail": detail})
        if not passed and blocked_by is None:
            blocked_by = name

    try:
        account = get_account_profile() or {}
    except Exception:
        account = {}
    try:
        positions = list_positions() or []
    except Exception:
        positions = []
    open_orders = []
    if asset_class_lc == "stock":
        try:
            open_orders = rh.get_all_open_stock_orders() or []
        except Exception:
            open_orders = []
    try:
        market = get_market_status()
    except Exception:
        market = {"session": "unknown"}

    equity = _to_float(account.get("equity"), 0.0)
    buying_power = _to_float(account.get("buying_power"), 0.0)
    market_value = _to_float(account.get("market_value"), 0.0)
    account_data_available = bool(account)
    if equity <= 0:
        equity = max(0.0, buying_power + market_value)

    ref_price = _to_float(price, 0.0)
    if ref_price <= 0:
        ref_price = _first_quote_price(symbol_up)
    order_notional = max(0.0, _to_float(qty, 0.0) * ref_price)

    symbol_equity_now = sum(
        _to_float(pos.get("equity"), 0.0)
        for pos in positions
        if str(pos.get("symbol", "")).upper() == symbol_up
    )
    symbol_equity_after = symbol_equity_now + (order_notional if side_lc == "buy" else -order_notional)
    if symbol_equity_after < 0:
        symbol_equity_after = 0.0

    intraday_pl_open_positions = sum(_to_float(pos.get("intraday_profit_loss"), 0.0) for pos in positions)
    equity_previous_close = _to_float(account.get("equity_previous_close"), 0.0)
    if equity_previous_close > 0 and equity > 0:
        daily_pnl_total = equity - equity_previous_close
        daily_pnl_source = "equity_vs_previous_close"
    else:
        daily_pnl_total = intraday_pl_open_positions
        daily_pnl_source = "open_positions_intraday_sum"
    daily_loss_breach = equity > 0 and daily_pnl_total <= -(equity * max_daily_loss_pct)

    pending_for_symbol = 0
    if asset_class_lc == "stock":
        for order in open_orders:
            order_symbol = str(order.get("symbol") or "").upper().strip()
            if not order_symbol:
                try:
                    order_symbol = str(rh.get_symbol_by_url(order.get("instrument")) or "").upper().strip()
                except Exception:
                    order_symbol = ""
            if order_symbol == symbol_up:
                pending_for_symbol += 1

    add_check(
        "buying_power",
        side_lc != "buy" or not account_data_available or buying_power >= order_notional,
        f"buying_power={buying_power:.2f}, order_notional={order_notional:.2f}",
    )
    add_check(
        "daily_loss_limit",
        side_lc != "buy" or not account_data_available or not daily_loss_breach,
        (
            f"daily_pnl_total={daily_pnl_total:.2f}, "
            f"source={daily_pnl_source}, "
            f"max_loss_allowed={-(equity * max_daily_loss_pct):.2f}"
        ),
    )
    add_check(
        "order_notional_limit",
        side_lc != "buy"
        or not account_data_available
        or equity <= 0
        or order_notional <= equity * max_order_notional_pct,
        (
            f"order_notional={order_notional:.2f}, "
            f"max_order_notional={equity * max_order_notional_pct:.2f}"
        ),
    )
    add_check(
        "symbol_exposure_limit",
        side_lc != "buy"
        or not account_data_available
        or equity <= 0
        or symbol_equity_after <= equity * max_symbol_exposure_pct,
        (
            f"symbol_equity_after={symbol_equity_after:.2f}, "
            f"max_symbol_equity={equity * max_symbol_exposure_pct:.2f}"
        ),
    )
    if asset_class_lc == "stock":
        add_check(
            "pending_order_limit",
            pending_for_symbol < max_pending_orders_per_symbol,
            f"pending_for_symbol={pending_for_symbol}, max={max_pending_orders_per_symbol}",
        )
    else:
        add_check(
            "pending_order_limit",
            True,
            "asset_class=crypto (stock pending-order cap bypassed)",
        )

    session = str(market.get("session") or "").lower()
    session_ok = True
    if (
        asset_class_lc == "stock"
        and session
        and session != "unknown"
        and not extended_hours
        and order_type == "market"
        and side_lc == "buy"
    ):
        session_ok = session == "regular"
    add_check(
        "market_session",
        session_ok,
        f"asset_class={asset_class_lc}, session={market.get('session')}, extended_hours={extended_hours}",
    )

    sentiment_summary = None
    sentiment_ok = True
    if enable_sentiment_guardrail and side_lc == "buy" and asset_class_lc == "stock":
        try:
            snapshot = get_reddit_sentiment_snapshot(
                symbols=symbol_up,
                lookback_hours=24,
                baseline_days=30,
                limit_posts=120,
            )
            rows = snapshot.get("symbols") or []
            if rows:
                row = rows[0]
                sentiment_summary = {
                    "symbol": row.get("symbol"),
                    "sentiment_score": row.get("sentiment_score"),
                    "hype_risk": row.get("hype_risk"),
                    "confidence": row.get("confidence"),
                }
                sentiment_ok = not (
                    row.get("hype_risk") == "high"
                    and _to_float(row.get("confidence"), 0.0) < sentiment_confidence_floor
                )
            elif sentiment_fail_closed:
                sentiment_ok = False
            add_check(
                "sentiment_guardrail",
                sentiment_ok,
                (
                    f"fail_closed={int(sentiment_fail_closed)}, "
                    f"hype_risk={(sentiment_summary or {}).get('hype_risk')}, "
                    f"confidence={(sentiment_summary or {}).get('confidence')}, "
                    f"floor={sentiment_confidence_floor}"
                ),
            )
        except Exception as e:
            add_check(
                "sentiment_guardrail",
                not sentiment_fail_closed,
                f"fail_closed={int(sentiment_fail_closed)}, sentiment unavailable: {str(e)}",
            )
    elif enable_sentiment_guardrail and side_lc == "buy":
        add_check("sentiment_guardrail", True, f"asset_class={asset_class_lc} (guardrail bypassed)")

    allowed = blocked_by is None
    reason = (
        "Pre-trade policy checks passed."
        if allowed
        else f"Blocked by pre-trade policy: {blocked_by}."
    )
    return {
        "allowed": allowed,
        "blocked_by": blocked_by,
        "reason": reason,
        "checks": checks,
        "metrics": {
            "symbol": symbol_up,
            "asset_class": asset_class_lc,
            "side": side_lc,
            "order_type": order_type,
            "qty": _to_float(qty, 0.0),
            "reference_price": ref_price,
            "order_notional": order_notional,
            "equity": equity,
            "equity_previous_close": equity_previous_close if equity_previous_close > 0 else None,
            "buying_power": buying_power,
            "intraday_pl_open_positions": intraday_pl_open_positions,
            "daily_pnl_total": daily_pnl_total,
            "daily_pnl_source": daily_pnl_source,
            "symbol_equity_before": symbol_equity_now,
            "symbol_equity_after": symbol_equity_after,
            "market_session": market.get("session"),
            "sentiment": sentiment_summary,
        },
        "limits": {
            "max_daily_loss_pct": max_daily_loss_pct,
            "max_order_notional_pct": max_order_notional_pct,
            "max_symbol_exposure_pct": max_symbol_exposure_pct,
            "max_pending_orders_per_symbol": max_pending_orders_per_symbol,
            "sentiment_fail_closed": sentiment_fail_closed,
            "sentiment_confidence_floor": sentiment_confidence_floor,
        },
    }
