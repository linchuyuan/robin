"""
Backtest engine for the quant strategy.

Improvements vs prior version:
- next-bar execution (signal at t-1 close, trade at t open)
- slippage and per-trade commission
- SPY benchmark comparison
- non-neutralized options/regime factor proxy
- risk metrics (Sharpe, Information Ratio, max drawdown)
- walk-forward out-of-sample protocol with threshold tuning
"""
from __future__ import annotations

import argparse
from datetime import datetime
import math

import numpy as np
import pandas as pd
import yfinance as yf

# --- Universe / period ---
SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "AMD", "NFLX"]
BENCHMARK = "SPY"
START_DATE = "2024-01-01"
END_DATE = datetime.now().strftime("%Y-%m-%d")

# --- Portfolio / risk ---
INITIAL_CAPITAL = 10_000.0
ENTRY_THRESHOLD = 70
MAX_POSITION_PCT = 0.15
MAX_OPEN_POSITIONS = 6
MAX_NEW_TRADES_PER_DAY = 1
CASH_BUFFER_PCT = 0.20
STOP_LOSS_PCT = 0.08

# --- Execution assumptions ---
SLIPPAGE_BPS = 5.0
FEE_PER_TRADE = 1.0
TRADING_DAYS = 252


def _slippage_factor() -> float:
    return SLIPPAGE_BPS / 10_000.0


def _max_drawdown(equity_series: pd.Series) -> float:
    rolling_max = equity_series.cummax()
    drawdown = (equity_series / rolling_max) - 1.0
    return float(drawdown.min()) if not drawdown.empty else 0.0


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def fetch_data(symbols: list[str], benchmark: str, start: str, end: str) -> pd.DataFrame:
    all_symbols = sorted(set([s.upper() for s in symbols] + [benchmark.upper()]))
    print(f"Fetching {len(all_symbols)} symbols from {start} to {end}...")
    data = yf.download(all_symbols, start=start, end=end, progress=True, auto_adjust=True)
    if data is None or data.empty:
        raise RuntimeError("No market data returned.")
    return data


def _extract_series(data: pd.DataFrame, field: str, symbol: str) -> pd.Series:
    symbol = symbol.upper()
    if isinstance(data.columns, pd.MultiIndex):
        return data[field][symbol]
    if field in data.columns:
        column = data[field]
        if isinstance(column, pd.DataFrame) and symbol in column.columns:
            return column[symbol]
        if isinstance(column, pd.Series):
            return column
    if symbol in data.columns:
        column = data[symbol]
        if isinstance(column, pd.Series):
            return column
    raise KeyError(f"Unable to extract {field} for {symbol}")


def calculate_features(close: pd.Series, high: pd.Series, low: pd.Series, volume: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame(index=close.index)
    df["Close"] = pd.to_numeric(close, errors="coerce")
    df["High"] = pd.to_numeric(high, errors="coerce")
    df["Low"] = pd.to_numeric(low, errors="coerce")
    df["Volume"] = pd.to_numeric(volume, errors="coerce")

    df["ret_5d"] = df["Close"].pct_change(5)
    df["ret_20d"] = df["Close"].pct_change(20)
    df["sma_50"] = df["Close"].rolling(window=50).mean()
    df["sma_200"] = df["Close"].rolling(window=200).mean()
    df["dist_sma_50"] = (df["Close"] - df["sma_50"]) / df["sma_50"]
    df["dist_sma_200"] = (df["Close"] - df["sma_200"]) / df["sma_200"]

    delta = df["Close"].diff()
    gains = delta.where(delta > 0, 0.0)
    losses = -delta.where(delta < 0, 0.0)
    avg_gain = gains.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df["rsi_14"] = 100 - (100 / (1 + rs))

    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - df["Close"].shift()).abs()
    tr3 = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr_14"] = tr.rolling(window=14).mean()
    df["atr_pct"] = (df["atr_14"] / df["Close"]).replace([np.inf, -np.inf], np.nan)

    df["vol_20d_avg"] = df["Volume"].rolling(window=20).mean().shift(1)
    df["rel_vol"] = df["Volume"] / df["vol_20d_avg"]

    df["vol_20d"] = df["Close"].pct_change().rolling(window=20).std() * math.sqrt(TRADING_DAYS)

    return df


def score_row(row: pd.Series) -> float:
    if row.isna().any():
        return float("nan")

    score = 0.0

    # --- Momentum (35) ---
    if row["dist_sma_50"] > 0:
        score += 10
    if row["rsi_14"] > 50:
        score += 8
    if row["ret_5d"] > 0:
        score += 7
    if row["ret_20d"] > 0:
        score += 10

    # --- Quality / structure (25) ---
    if row["dist_sma_200"] > 0:
        score += 10
    if 45 <= row["rsi_14"] <= 70:
        score += 8
    if row["atr_pct"] < 0.04:
        score += 7

    # --- Catalyst / participation (20) ---
    if row["rel_vol"] > 1.8:
        score += 12
    elif row["rel_vol"] > 1.2:
        score += 8
    if row["ret_5d"] > 0 and row["ret_20d"] > 0:
        score += 8

    # --- Options / regime proxy (20) ---
    # Favor trend persistence with contained realized volatility.
    if row["vol_20d"] <= 0.25 and row["ret_20d"] > 0:
        score += 20
    elif row["vol_20d"] <= 0.35 and row["ret_20d"] > 0:
        score += 12
    elif row["vol_20d"] <= 0.45:
        score += 6

    return min(100.0, max(0.0, score))


def _build_symbol_data(raw: pd.DataFrame) -> tuple[pd.Series, pd.Index, dict[str, dict[str, pd.Series | pd.DataFrame]]]:
    benchmark_close = _extract_series(raw, "Close", BENCHMARK).dropna()
    dates = benchmark_close.index
    if len(dates) < 252:
        raise RuntimeError("Insufficient benchmark history for robust metrics.")

    symbol_data: dict[str, dict[str, pd.Series | pd.DataFrame]] = {}
    for symbol in SYMBOLS:
        try:
            open_series = _extract_series(raw, "Open", symbol)
            close_series = _extract_series(raw, "Close", symbol)
            high_series = _extract_series(raw, "High", symbol)
            low_series = _extract_series(raw, "Low", symbol)
            vol_series = _extract_series(raw, "Volume", symbol)

            features = calculate_features(close_series, high_series, low_series, vol_series)
            features["score"] = features.apply(score_row, axis=1)

            symbol_data[symbol] = {
                "open": open_series.reindex(dates).ffill(),
                "close": close_series.reindex(dates).ffill(),
                "features": features.reindex(dates).ffill(),
            }
        except Exception as e:
            print(f"Skipping {symbol}: {e}")

    return benchmark_close, dates, symbol_data


def _simulate_on_dates(
    *,
    dates: pd.Index,
    benchmark_close: pd.Series,
    symbol_data: dict[str, dict[str, pd.Series | pd.DataFrame]],
    entry_threshold: int = ENTRY_THRESHOLD,
    max_position_pct: float = MAX_POSITION_PCT,
    stop_loss_pct: float = STOP_LOSS_PCT,
) -> dict:
    if len(dates) < 2:
        raise RuntimeError("Need at least two dates to simulate.")
    if not symbol_data:
        raise RuntimeError("No symbols with usable data.")

    cash = INITIAL_CAPITAL
    positions: dict[str, dict[str, float]] = {}
    history: list[dict] = [{"date": dates[0], "equity": INITIAL_CAPITAL, "cash": INITIAL_CAPITAL, "positions": 0}]
    trades: list[dict] = []
    slip = _slippage_factor()

    print("Starting simulation...")
    for index in range(1, len(dates)):
        date = dates[index]
        prev_date = dates[index - 1]

        # 1) Mark-to-market and exits on current close.
        for symbol in list(positions.keys()):
            close_price = float(symbol_data[symbol]["close"].loc[date])
            entry_price = float(positions[symbol]["entry_price"])
            quantity = int(positions[symbol]["qty"])

            if close_price <= entry_price * (1.0 - stop_loss_pct):
                exit_price = close_price * (1.0 - slip)
                proceeds = quantity * exit_price - FEE_PER_TRADE
                cash += max(0.0, proceeds)
                trades.append(
                    {
                        "date": date,
                        "symbol": symbol,
                        "side": "SELL_STOP",
                        "qty": quantity,
                        "price": round(exit_price, 4),
                        "notional": round(quantity * exit_price, 2),
                    }
                )
                del positions[symbol]

        # 2) Build candidate list from previous-day signals (no lookahead).
        equity = cash
        for symbol, position in positions.items():
            close_price = float(symbol_data[symbol]["close"].loc[date])
            equity += position["qty"] * close_price

        candidates: list[tuple[str, float, float]] = []
        if len(positions) < MAX_OPEN_POSITIONS:
            for symbol, payload in symbol_data.items():
                if symbol in positions:
                    continue
                signal_row = payload["features"].loc[prev_date]
                signal_score = signal_row.get("score")
                if pd.isna(signal_score) or float(signal_score) < int(entry_threshold):
                    continue
                next_open = float(payload["open"].loc[date])
                if next_open <= 0:
                    continue
                candidates.append((symbol, float(signal_score), next_open))

        candidates.sort(key=lambda item: item[1], reverse=True)

        # 3) Enter at current open with slippage and commissions.
        cash_buffer = equity * CASH_BUFFER_PCT
        spendable_cash = max(0.0, cash - cash_buffer)
        opened = 0
        for symbol, score, next_open in candidates:
            if opened >= MAX_NEW_TRADES_PER_DAY:
                break
            if len(positions) >= MAX_OPEN_POSITIONS:
                break
            if spendable_cash <= 0:
                break

            exec_price = next_open * (1.0 + slip)
            target_notional = min(equity * float(max_position_pct), spendable_cash)
            qty = int(max(0.0, target_notional - FEE_PER_TRADE) / exec_price)
            if qty <= 0:
                continue

            total_cost = qty * exec_price + FEE_PER_TRADE
            if total_cost > cash:
                continue

            cash -= total_cost
            spendable_cash = max(0.0, spendable_cash - total_cost)
            positions[symbol] = {"qty": qty, "entry_price": exec_price, "entry_date": date}
            opened += 1
            trades.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "side": "BUY",
                    "qty": qty,
                    "price": round(exec_price, 4),
                    "score": round(score, 2),
                    "notional": round(qty * exec_price, 2),
                }
            )

        # 4) End-of-day equity snapshot.
        end_equity = cash
        for symbol, position in positions.items():
            end_equity += position["qty"] * float(symbol_data[symbol]["close"].loc[date])
        history.append({"date": date, "equity": end_equity, "cash": cash, "positions": len(positions)})

    history_df = pd.DataFrame(history).set_index("date")
    strategy_curve = history_df["equity"]
    strategy_returns = strategy_curve.pct_change().dropna()

    benchmark_curve = (benchmark_close.reindex(strategy_curve.index).ffill() / benchmark_close.iloc[0]) * INITIAL_CAPITAL
    benchmark_returns = benchmark_curve.pct_change().dropna()

    strategy_total_return = _safe_div(strategy_curve.iloc[-1], INITIAL_CAPITAL) - 1.0
    benchmark_total_return = _safe_div(benchmark_curve.iloc[-1], INITIAL_CAPITAL) - 1.0
    excess_return = strategy_total_return - benchmark_total_return

    strategy_sharpe = (
        float(np.sqrt(TRADING_DAYS) * strategy_returns.mean() / strategy_returns.std())
        if strategy_returns.std() and not np.isnan(strategy_returns.std())
        else 0.0
    )
    strat_aligned, bench_aligned = strategy_returns.align(benchmark_returns, join="inner")
    active_returns = strat_aligned - bench_aligned
    info_ratio = (
        float(np.sqrt(TRADING_DAYS) * active_returns.mean() / active_returns.std())
        if active_returns.std() and not np.isnan(active_returns.std())
        else 0.0
    )
    max_drawdown = _max_drawdown(strategy_curve)

    results = {
        "start_date": str(strategy_curve.index[0].date()),
        "end_date": str(strategy_curve.index[-1].date()),
        "symbols_considered": sorted(symbol_data.keys()),
        "initial_capital": INITIAL_CAPITAL,
        "final_equity": round(float(strategy_curve.iloc[-1]), 2),
        "strategy_return_pct": round(strategy_total_return * 100.0, 2),
        "benchmark": BENCHMARK,
        "benchmark_return_pct": round(benchmark_total_return * 100.0, 2),
        "excess_return_pct": round(excess_return * 100.0, 2),
        "strategy_sharpe": round(strategy_sharpe, 3),
        "information_ratio": round(info_ratio, 3),
        "max_drawdown_pct": round(max_drawdown * 100.0, 2),
        "trades": len(trades),
    }
    return results


def run_backtest() -> dict:
    raw = fetch_data(SYMBOLS, BENCHMARK, START_DATE, END_DATE)
    benchmark_close, dates, symbol_data = _build_symbol_data(raw)
    results = _simulate_on_dates(dates=dates, benchmark_close=benchmark_close, symbol_data=symbol_data)
    results.update(
        {
            "start_date": str(dates[0].date()),
            "end_date": str(dates[-1].date()),
            "symbols_considered": sorted(symbol_data.keys()),
        }
    )
    print("\n--- Backtest Summary ---")
    for key, value in results.items():
        print(f"{key}: {value}")
    return results


def _select_threshold_for_train(
    *,
    train_dates: pd.Index,
    benchmark_close: pd.Series,
    symbol_data: dict[str, dict[str, pd.Series | pd.DataFrame]],
    threshold_grid: list[int],
) -> tuple[int, dict]:
    best_threshold = threshold_grid[0]
    best_metrics = None
    best_score = float("-inf")
    for threshold in threshold_grid:
        metrics = _simulate_on_dates(
            dates=train_dates,
            benchmark_close=benchmark_close,
            symbol_data=symbol_data,
            entry_threshold=threshold,
        )
        score = float(metrics.get("strategy_sharpe", 0.0)) + float(metrics.get("excess_return_pct", 0.0)) / 100.0
        if best_metrics is None or score > best_score:
            best_score = score
            best_threshold = threshold
            best_metrics = metrics
    return best_threshold, best_metrics or {}


def run_walk_forward_backtest(
    *,
    train_days: int = 252,
    test_days: int = 63,
    step_days: int = 63,
    threshold_grid: list[int] | None = None,
) -> dict:
    grid = sorted(set(int(x) for x in (threshold_grid or [65, 70, 75])))
    if not grid:
        raise RuntimeError("threshold_grid must contain at least one threshold.")
    if train_days < 120 or test_days < 20 or step_days < 10:
        raise RuntimeError("Use realistic windows: train_days>=120, test_days>=20, step_days>=10.")

    raw = fetch_data(SYMBOLS, BENCHMARK, START_DATE, END_DATE)
    benchmark_close, all_dates, symbol_data = _build_symbol_data(raw)
    if len(all_dates) < (train_days + test_days + 1):
        raise RuntimeError("Insufficient history for requested walk-forward windows.")
    if not symbol_data:
        raise RuntimeError("No symbols with usable data.")

    windows: list[dict] = []
    index = 0
    while index + train_days + test_days <= len(all_dates):
        split = index + train_days
        test_end = split + test_days

        train_dates = all_dates[index:split]
        test_dates = all_dates[split - 1:test_end]
        if len(test_dates) < 2:
            break

        selected_threshold, train_metrics = _select_threshold_for_train(
            train_dates=train_dates,
            benchmark_close=benchmark_close,
            symbol_data=symbol_data,
            threshold_grid=grid,
        )
        oos_metrics = _simulate_on_dates(
            dates=test_dates,
            benchmark_close=benchmark_close,
            symbol_data=symbol_data,
            entry_threshold=selected_threshold,
        )
        windows.append(
            {
                "train_start": str(train_dates[0].date()),
                "train_end": str(train_dates[-1].date()),
                "test_start": str(test_dates[1].date()),
                "test_end": str(test_dates[-1].date()),
                "selected_entry_threshold": selected_threshold,
                "train_strategy_sharpe": train_metrics.get("strategy_sharpe"),
                "train_excess_return_pct": train_metrics.get("excess_return_pct"),
                "oos_strategy_return_pct": oos_metrics.get("strategy_return_pct"),
                "oos_benchmark_return_pct": oos_metrics.get("benchmark_return_pct"),
                "oos_excess_return_pct": oos_metrics.get("excess_return_pct"),
                "oos_strategy_sharpe": oos_metrics.get("strategy_sharpe"),
                "oos_information_ratio": oos_metrics.get("information_ratio"),
                "oos_max_drawdown_pct": oos_metrics.get("max_drawdown_pct"),
                "oos_trades": oos_metrics.get("trades"),
            }
        )
        index += step_days

    if not windows:
        raise RuntimeError("No valid walk-forward windows could be produced.")

    compounded_strategy = 1.0
    compounded_benchmark = 1.0
    threshold_counts: dict[int, int] = {}
    for window in windows:
        compounded_strategy *= 1.0 + float(window["oos_strategy_return_pct"]) / 100.0
        compounded_benchmark *= 1.0 + float(window["oos_benchmark_return_pct"]) / 100.0
        t = int(window["selected_entry_threshold"])
        threshold_counts[t] = threshold_counts.get(t, 0) + 1

    avg_oos_sharpe = float(np.mean([float(w["oos_strategy_sharpe"]) for w in windows]))
    avg_oos_info_ratio = float(np.mean([float(w["oos_information_ratio"]) for w in windows]))
    avg_oos_drawdown = float(np.mean([float(w["oos_max_drawdown_pct"]) for w in windows]))

    results = {
        "mode": "walk_forward",
        "start_date": str(all_dates[0].date()),
        "end_date": str(all_dates[-1].date()),
        "symbols_considered": sorted(symbol_data.keys()),
        "windows": len(windows),
        "train_days": int(train_days),
        "test_days": int(test_days),
        "step_days": int(step_days),
        "threshold_grid": grid,
        "threshold_selection_counts": threshold_counts,
        "oos_compounded_strategy_return_pct": round((compounded_strategy - 1.0) * 100.0, 2),
        "oos_compounded_benchmark_return_pct": round((compounded_benchmark - 1.0) * 100.0, 2),
        "oos_compounded_excess_return_pct": round((compounded_strategy - compounded_benchmark) * 100.0, 2),
        "oos_avg_sharpe": round(avg_oos_sharpe, 3),
        "oos_avg_information_ratio": round(avg_oos_info_ratio, 3),
        "oos_avg_max_drawdown_pct": round(avg_oos_drawdown, 2),
        "window_results": windows,
    }

    print("\n--- Walk-Forward Summary ---")
    for key in [
        "mode",
        "start_date",
        "end_date",
        "symbols_considered",
        "windows",
        "train_days",
        "test_days",
        "step_days",
        "threshold_grid",
        "threshold_selection_counts",
        "oos_compounded_strategy_return_pct",
        "oos_compounded_benchmark_return_pct",
        "oos_compounded_excess_return_pct",
        "oos_avg_sharpe",
        "oos_avg_information_ratio",
        "oos_avg_max_drawdown_pct",
    ]:
        print(f"{key}: {results[key]}")
    print("\nWindow details:")
    for row in windows:
        print(
            f"{row['test_start']} -> {row['test_end']} | thr={row['selected_entry_threshold']} | "
            f"oos_excess={row['oos_excess_return_pct']}% | sharpe={row['oos_strategy_sharpe']} | "
            f"mdd={row['oos_max_drawdown_pct']}% | trades={row['oos_trades']}"
        )
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run quant strategy backtest.")
    parser.add_argument("--mode", choices=["single", "walk-forward"], default="single")
    parser.add_argument("--train-days", type=int, default=252)
    parser.add_argument("--test-days", type=int, default=63)
    parser.add_argument("--step-days", type=int, default=63)
    parser.add_argument(
        "--threshold-grid",
        default="65,70,75",
        help="Comma-separated entry thresholds for walk-forward tuning (e.g. 65,70,75).",
    )
    args = parser.parse_args()

    if args.mode == "walk-forward":
        thresholds = [int(x.strip()) for x in str(args.threshold_grid).split(",") if x.strip()]
        run_walk_forward_backtest(
            train_days=args.train_days,
            test_days=args.test_days,
            step_days=args.step_days,
            threshold_grid=thresholds,
        )
    else:
        run_backtest()
