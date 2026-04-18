"""
Live-vs-backtest drift monitor. Records actual fill slippage and compares it
against the slippage-curve model and backtest assumptions. Surfaces drift so
the slippage model can be recalibrated (via env vars in execution_models).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from execution_models import estimate_slippage_bps
except ImportError:
    estimate_slippage_bps = None


_DRIFT_FILE = os.getenv(
    "ROBIN_DRIFT_FILE",
    str(Path(__file__).parent / "memory" / "live-vs-backtest.json"),
)


def _load_drift_state() -> dict:
    try:
        p = Path(_DRIFT_FILE)
        if p.exists():
            with open(p, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {"fills": [], "stats": {}}


def _save_drift_state(state: dict) -> None:
    p = Path(_DRIFT_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(state, f, indent=2)


def record_live_fill(
    *,
    symbol: str,
    side: str,
    quantity: float,
    requested_price: float,
    avg_fill_price: float,
    order_notional_usd: float,
    adv_usd_estimate: float | None = None,
    vol_20d_annual: float | None = None,
    minute_of_day: int | None = None,
    order_type: str = "market",
) -> dict:
    """
    Record a live fill and compare it against the slippage model's prediction.
    """
    if requested_price <= 0 or avg_fill_price <= 0:
        return {"recorded": False, "reason": "invalid_prices"}

    side_lc = side.lower()
    # Slippage bps: positive = worse than requested
    if side_lc == "buy":
        actual_bps = ((avg_fill_price - requested_price) / requested_price) * 10_000
    else:
        actual_bps = ((requested_price - avg_fill_price) / requested_price) * 10_000

    predicted_bps = None
    prediction = None
    if estimate_slippage_bps is not None and adv_usd_estimate is not None and vol_20d_annual is not None:
        prediction = estimate_slippage_bps(
            order_notional_usd=order_notional_usd,
            adv_usd=adv_usd_estimate,
            vol_20d_annual=vol_20d_annual,
            minute_of_day=minute_of_day,
        )
        predicted_bps = prediction["slippage_bps"]

    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "symbol": symbol.upper(),
        "side": side_lc,
        "order_type": order_type,
        "quantity": float(quantity),
        "requested_price": requested_price,
        "avg_fill_price": avg_fill_price,
        "order_notional_usd": order_notional_usd,
        "actual_slippage_bps": round(actual_bps, 2),
        "predicted_slippage_bps": predicted_bps,
        "prediction_details": prediction,
        "drift_bps": round(actual_bps - predicted_bps, 2) if predicted_bps is not None else None,
    }

    state = _load_drift_state()
    state.setdefault("fills", []).append(record)
    # Retain the last 500 fills
    if len(state["fills"]) > 500:
        state["fills"] = state["fills"][-500:]
    state["stats"] = compute_drift_stats(state["fills"])
    _save_drift_state(state)
    return {"recorded": True, "record": record}


def compute_drift_stats(fills: list[dict]) -> dict:
    """Summarize drift across recorded fills."""
    if not fills:
        return {"samples": 0}

    valid = [f for f in fills if f.get("actual_slippage_bps") is not None]
    if not valid:
        return {"samples": 0}

    actual = [f["actual_slippage_bps"] for f in valid]
    mean_actual = sum(actual) / len(actual)
    # Median without numpy
    sorted_actual = sorted(actual)
    mid = len(sorted_actual) // 2
    median_actual = (
        sorted_actual[mid]
        if len(sorted_actual) % 2
        else (sorted_actual[mid - 1] + sorted_actual[mid]) / 2
    )

    with_pred = [f for f in valid if f.get("predicted_slippage_bps") is not None]
    mean_drift = None
    if with_pred:
        drifts = [f["drift_bps"] for f in with_pred if f.get("drift_bps") is not None]
        if drifts:
            mean_drift = sum(drifts) / len(drifts)

    return {
        "samples": len(valid),
        "samples_with_prediction": len(with_pred),
        "mean_actual_slippage_bps": round(mean_actual, 2),
        "median_actual_slippage_bps": round(median_actual, 2),
        "mean_drift_bps": round(mean_drift, 2) if mean_drift is not None else None,
        "recommendation": _recommendation(mean_actual, mean_drift),
    }


def _recommendation(mean_actual: float, mean_drift: float | None) -> str:
    if mean_drift is None:
        return "insufficient_prediction_pairs_yet"
    if abs(mean_drift) < 3:
        return "calibrated_well"
    if mean_drift > 10:
        return "real_slippage_materially_worse_than_model; increase impact_coef ~20%"
    if mean_drift < -10:
        return "real_slippage_better_than_model; consider lowering impact_coef ~10%"
    if mean_drift > 3:
        return "slight_underestimate; monitor"
    return "slight_overestimate; monitor"


def get_drift_report() -> dict:
    state = _load_drift_state()
    return {
        "fill_count": len(state.get("fills", [])),
        "stats": state.get("stats", {}),
        "last_5_fills": (state.get("fills") or [])[-5:],
    }
