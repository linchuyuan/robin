"""Decision confidence calibration from stored decision traces."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if hasattr(value, "iloc"):
            value = value.iloc[0]
        if value in ("", None):
            return default
        return float(value)
    except Exception:
        return default


def _bucket(confidence: Any, conviction: Any = None) -> str | None:
    raw = confidence if confidence not in (None, "") else conviction
    if raw in (None, ""):
        return None
    if isinstance(raw, (int, float)):
        if raw >= 0.70:
            return "high"
        if raw >= 0.55:
            return "moderate"
        return "low"
    text = str(raw).lower().strip()
    if text in {"high", "strong", "tier1", "tier_1"}:
        return "high"
    if text in {"moderate", "medium", "mid", "tier2", "tier_2"}:
        return "moderate"
    if text in {"low", "weak", "watch", "tier3", "tier_3"}:
        return "low"
    return None


def _extract_outcome(decision: dict, horizon: str) -> tuple[float | None, float | None]:
    outcomes = decision.get("outcomes") if isinstance(decision.get("outcomes"), dict) else {}
    ret = _to_float(outcomes.get(horizon), _to_float(decision.get(horizon)))
    spy_key = horizon.replace("return", "spy_return")
    bench_key = horizon.replace("return", "benchmark_return")
    benchmark = _to_float(
        outcomes.get(spy_key),
        _to_float(
            outcomes.get(bench_key),
            _to_float(
                decision.get(spy_key),
                _to_float(decision.get(bench_key)),
            ),
        ),
    )
    return ret, benchmark


def flatten_trace_decisions(trace: dict) -> list[dict]:
    if not isinstance(trace, dict):
        return []
    if isinstance(trace.get("decisions"), list):
        return [d for d in trace["decisions"] if isinstance(d, dict)]
    if isinstance(trace.get("actions"), list):
        return [d for d in trace["actions"] if isinstance(d, dict)]
    return [trace]


def compute_confidence_calibration(traces: list[dict], horizon: str = "d5_return") -> dict:
    buckets = {
        "high": {"sample_size": 0, "wins": 0, "returns": [], "excess_returns": []},
        "moderate": {"sample_size": 0, "wins": 0, "returns": [], "excess_returns": []},
        "low": {"sample_size": 0, "wins": 0, "returns": [], "excess_returns": []},
    }
    skipped = 0
    for trace in traces:
        for decision in flatten_trace_decisions(trace):
            side = str(decision.get("side") or decision.get("action") or "").lower()
            if side and not any(token in side for token in ("buy", "long", "add")):
                skipped += 1
                continue
            bucket = _bucket(decision.get("predicted_confidence"), decision.get("confidence") or decision.get("conviction"))
            ret, benchmark = _extract_outcome(decision, horizon)
            if bucket is None or ret is None:
                skipped += 1
                continue
            excess = ret - benchmark if benchmark is not None else ret
            row = buckets[bucket]
            row["sample_size"] += 1
            row["returns"].append(ret)
            row["excess_returns"].append(excess)
            if excess > 0:
                row["wins"] += 1

    summarized = {}
    for name, row in buckets.items():
        n = row["sample_size"]
        summarized[name] = {
            "sample_size": n,
            "win_rate_vs_benchmark": round(row["wins"] / n, 3) if n else None,
            "avg_return": round(sum(row["returns"]) / n, 4) if n else None,
            "avg_excess_return": round(sum(row["excess_returns"]) / n, 4) if n else None,
        }

    high = summarized["high"]
    moderate = summarized["moderate"]
    recommendations: list[str] = []
    if high["sample_size"] >= 10 and (high["win_rate_vs_benchmark"] or 0) < 0.55:
        recommendations.append("downshift_high_confidence: high-confidence decisions are not clearing benchmark often enough")
    if moderate["sample_size"] >= 10 and (moderate["win_rate_vs_benchmark"] or 0) < 0.50:
        recommendations.append("raise_moderate_threshold: moderate-confidence decisions are underperforming benchmark")
    if not recommendations:
        recommendations.append("insufficient_or_ok: keep collecting samples unless other risk controls fire")

    total = sum(row["sample_size"] for row in summarized.values())
    return {
        "available": total > 0,
        "horizon": horizon,
        "sample_size": total,
        "skipped_decisions": skipped,
        "buckets": summarized,
        "recommendations": recommendations,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
