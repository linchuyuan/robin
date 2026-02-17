import json

from quant import get_peers, get_sector_performance, get_technical_indicators


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
        "return_5d",
        "return_20d",
        "relative_volume",
        "timestamp",
        "timezone",
    ]
    for key in required:
        _assert(key in res, f"Missing key in technical indicators: {key}")
    _assert(res.get("timezone") == "UTC", "Technical indicators timezone should be UTC")


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
    test_sector_perf()
    test_peers()
    print("\nAll quant contract tests passed.")
