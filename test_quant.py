import json

from quant import get_peers, get_sector_performance, get_technical_indicators, get_volume_velocity


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_tech_ind() -> None:
    print("Testing get_technical_indicators('AAPL')...")
    res = get_technical_indicators("AAPL")
    print(json.dumps(res, indent=2))

    _assert("error" not in res, f"Technical indicators returned error: {res.get('error')}")
    required = [
        "symbol",
        "price",
        "sma_50",
        "sma_200",
        "rsi_14",
        "atr_14",
        "rs_spy_percentile",
        "return_5d",
        "return_20d",
        "relative_volume",
        "daily_relative_volume",
        "relative_volume_context",
        "volatility_sizing",
        "timestamp",
        "timezone",
    ]
    for key in required:
        _assert(key in res, f"Missing key in technical indicators: {key}")
    _assert(res.get("timezone") == "UTC", "Technical indicators timezone should be UTC")
    _assert(isinstance(res.get("volatility_sizing"), dict), "volatility_sizing should be a dict")
    _assert("suggested_shares_per_1k_risk" in res["volatility_sizing"], "volatility_sizing missing suggested shares")
    rs_pct = res.get("rs_spy_percentile")
    if rs_pct is not None:
        _assert(0 <= rs_pct <= 100, "rs_spy_percentile should be between 0 and 100")
    rel_ctx = res.get("relative_volume_context")
    _assert(isinstance(rel_ctx, dict), "relative_volume_context should be a dict")
    _assert(rel_ctx.get("valid_for") == "daily_or_near_close", "relative volume should be labeled daily/near-close")


def test_volume_velocity() -> None:
    print("\nTesting get_volume_velocity('AAPL')...")
    res = get_volume_velocity("AAPL", interval="5m", period="5d", baseline_bars=12, series_points=6)
    print(json.dumps(res, indent=2))

    _assert("error" not in res, f"Volume velocity returned error: {res.get('error')}")
    for key in ("symbol", "interval", "latest", "trend", "series", "data_quality", "timestamp", "timezone"):
        _assert(key in res, f"Missing key in volume velocity: {key}")
    latest = res["latest"]
    for key in ("volume", "baseline_avg_volume", "velocity_ratio", "classification", "baseline_type", "same_slot_sample_size"):
        _assert(key in latest, f"Missing latest volume velocity key: {key}")
    _assert(isinstance(res["series"], list), "volume velocity series should be a list")
    _assert(latest.get("baseline_type") in {"same_time_of_day", "rolling_prior_bars"}, "Unexpected baseline_type")


def test_sector_perf() -> None:
    print("\nTesting get_sector_performance()...")
    res = get_sector_performance()
    print(json.dumps(res, indent=2))

    _assert(isinstance(res, list), "Sector performance should return a list")
    _assert(len(res) > 0, "Sector performance returned empty list")
    _assert("error" not in res[0], f"Sector performance returned error: {res[0].get('error')}")
    for item in res:
        for key in ("symbol", "name", "return_5d"):
            _assert(key in item, f"Missing sector key: {key}")
    _assert(all(item.get("symbol") != "SPY" for item in res), "SPY benchmark should not be included as a sector")
    # Verify descending sort by return_5d.
    returns = [item["return_5d"] for item in res]
    _assert(returns == sorted(returns, reverse=True), "Sector performance is not sorted descending")


def test_peers() -> None:
    print("\nTesting get_peers('MSFT')...")
    res = get_peers("MSFT")
    print(json.dumps(res, indent=2))

    _assert("error" not in res, f"Peers returned error: {res.get('error')}")
    for key in ("symbol", "sector", "industry", "peers", "count"):
        _assert(key in res, f"Missing peers key: {key}")
    _assert(isinstance(res["peers"], list), "Peers should be a list")
    _assert(isinstance(res["count"], int), "Peers count should be int")
    _assert(res["count"] == len(res["peers"]), "Peers count does not match list length")


if __name__ == "__main__":
    test_tech_ind()
    test_volume_velocity()
    test_sector_perf()
    test_peers()
    print("\nAll quant contract tests passed.")
