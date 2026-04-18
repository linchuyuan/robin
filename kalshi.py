"""Read-only Kalshi market data helpers for trading context."""
from __future__ import annotations

import os
from typing import Any

import requests

DEFAULT_KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
DEFAULT_TIMEOUT_SECONDS = 8

ECONOMIC_CONTEXT_TERMS = {
    "all": ["inflation", "CPI", "Fed", "interest rates", "unemployment", "jobs", "GDP", "recession", "oil"],
    "global": ["recession", "oil", "China", "Europe", "geopolitical", "war", "global"],
    "economic": ["inflation", "CPI", "Fed", "interest rates", "unemployment", "jobs", "GDP", "recession"],
    "inflation": ["inflation", "CPI", "PCE"],
    "fed": ["Fed", "interest rates", "FOMC", "rate cut", "rate hike"],
    "jobs": ["unemployment", "jobs", "payrolls", "jobless"],
    "growth": ["GDP", "recession", "growth"],
    "energy": ["oil", "gas", "energy"],
}

STOCK_CONTEXT_TERMS = {
    "SPY": ["S&P 500", "stock market", "recession", "Fed", "interest rates", "inflation"],
    "QQQ": ["Nasdaq", "technology", "AI", "Fed", "interest rates"],
    "DIA": ["Dow", "stock market", "industrial"],
    "IWM": ["Russell", "small cap", "recession", "interest rates"],
    "AAPL": ["Apple", "iPhone"],
    "AMZN": ["Amazon"],
    "GOOG": ["Google", "Alphabet"],
    "GOOGL": ["Google", "Alphabet"],
    "META": ["Meta", "Facebook"],
    "MSFT": ["Microsoft", "AI"],
    "NVDA": ["Nvidia", "AI", "semiconductor"],
    "TSLA": ["Tesla", "EV"],
}


class KalshiError(RuntimeError):
    """Raised when Kalshi returns an unusable response."""


def _base_url() -> str:
    return os.getenv("KALSHI_API_BASE_URL", DEFAULT_KALSHI_BASE_URL).rstrip("/")


def _timeout_seconds() -> int:
    try:
        return max(1, int(float(os.getenv("KALSHI_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS


def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if value not in (None, "", [])}


def _get_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{_base_url()}/{path.lstrip('/')}"
    response = requests.get(url, params=_clean_params(params or {}), timeout=_timeout_seconds())
    if response.status_code >= 400:
        raise KalshiError(f"Kalshi request failed ({response.status_code}): {response.text[:300]}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise KalshiError("Kalshi response was not a JSON object.")
    return payload


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return float(default)
        result = float(value)
        return float(default) if result != result else result
    except (TypeError, ValueError):
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value in ("", None):
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _price_cents(market: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = market.get(key)
        if value in ("", None):
            continue
        numeric = _to_float(value, 0.0)
        if key.endswith("_dollars"):
            return int(round(numeric * 100))
        return int(round(numeric))
    return None


def _text_blob(market: dict[str, Any]) -> str:
    fields = [
        market.get("ticker"),
        market.get("event_ticker"),
        market.get("series_ticker"),
        market.get("title"),
        market.get("subtitle"),
        market.get("category"),
    ]
    return " ".join(str(value or "") for value in fields).lower()


def _matches_query(market: dict[str, Any], query: str) -> bool:
    terms = [part.strip().lower() for part in str(query or "").replace(",", " ").split() if part.strip()]
    if not terms:
        return True
    blob = _text_blob(market)
    return all(term in blob for term in terms)


def _dedupe_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    unique = []
    for market in markets:
        ticker = str(market.get("ticker") or "")
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        unique.append(market)
    return unique


def normalize_market(market: dict[str, Any]) -> dict[str, Any]:
    yes_bid = _price_cents(market, "yes_bid", "yes_bid_dollars")
    yes_ask = _price_cents(market, "yes_ask", "yes_ask_dollars")
    last_price = _price_cents(market, "last_price", "last_price_dollars")
    implied_mid = None
    if yes_bid is not None and yes_ask is not None:
        implied_mid = round((yes_bid + yes_ask) / 2, 2)
    elif last_price is not None:
        implied_mid = float(last_price)

    return {
        "ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        "series_ticker": market.get("series_ticker"),
        "title": market.get("title"),
        "subtitle": market.get("subtitle"),
        "category": market.get("category"),
        "status": market.get("status"),
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "last_price": last_price,
        "implied_probability_mid": implied_mid,
        "volume": _to_int(market.get("volume") or market.get("volume_fp"), 0),
        "open_interest": _to_int(market.get("open_interest"), 0),
        "liquidity": _to_int(market.get("liquidity"), 0),
        "close_time": market.get("close_time"),
        "raw": market,
    }


def list_kalshi_markets(
    *,
    status: str = "open",
    limit: int = 100,
    cursor: str | None = None,
    event_ticker: str | None = None,
    series_ticker: str | None = None,
    tickers: str | None = None,
) -> dict[str, Any]:
    payload = _get_json(
        "markets",
        {
            "status": status,
            "limit": max(1, min(int(limit), 1000)),
            "cursor": cursor,
            "event_ticker": event_ticker,
            "series_ticker": series_ticker,
            "tickers": tickers,
        },
    )
    markets = [normalize_market(item) for item in payload.get("markets", []) if isinstance(item, dict)]
    return {
        "markets": markets,
        "count": len(markets),
        "cursor": payload.get("cursor"),
    }


def search_kalshi_markets(
    query: str,
    *,
    status: str = "open",
    limit: int = 25,
    max_pages: int = 3,
) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    cursor = None
    page_count = 0
    page_limit = 200

    while len(selected) < limit and page_count < max(1, int(max_pages or 1)):
        page = list_kalshi_markets(status=status, limit=page_limit, cursor=cursor)
        page_count += 1
        selected.extend([market for market in page["markets"] if _matches_query(market, query)])
        cursor = page.get("cursor")
        if not cursor:
            break

    deduped = _dedupe_markets(selected)[: max(1, int(limit))]
    return {
        "query": query,
        "status": status,
        "markets": deduped,
        "count": len(deduped),
        "pages_scanned": page_count,
        "source": "kalshi_public_api",
    }


def get_kalshi_market(ticker: str, *, include_orderbook: bool = False, depth: int = 10) -> dict[str, Any]:
    symbol = str(ticker or "").upper().strip()
    if not symbol:
        raise ValueError("ticker is required.")
    payload = _get_json(f"markets/{symbol}")
    market = normalize_market(payload.get("market") or payload)
    result = {"market": market}
    if include_orderbook:
        result["orderbook"] = get_kalshi_orderbook(symbol, depth=depth).get("orderbook")
    return result


def get_kalshi_event(event_ticker: str) -> dict[str, Any]:
    ticker = str(event_ticker or "").upper().strip()
    if not ticker:
        raise ValueError("event_ticker is required.")
    return _get_json(f"events/{ticker}")


def get_kalshi_orderbook(ticker: str, *, depth: int = 10) -> dict[str, Any]:
    symbol = str(ticker or "").upper().strip()
    if not symbol:
        raise ValueError("ticker is required.")
    return _get_json(f"markets/{symbol}/orderbook", {"depth": max(1, min(int(depth), 100))})


def get_kalshi_economic_context(
    *,
    topic: str = "all",
    status: str = "open",
    limit: int = 25,
    max_pages_per_query: int = 2,
) -> dict[str, Any]:
    topic_key = str(topic or "all").strip().lower()
    terms = ECONOMIC_CONTEXT_TERMS.get(topic_key, [topic_key])
    markets: list[dict[str, Any]] = []
    for term in terms:
        result = search_kalshi_markets(term, status=status, limit=limit, max_pages=max_pages_per_query)
        markets.extend(result.get("markets", []))
        if len(_dedupe_markets(markets)) >= limit:
            break
    selected = _dedupe_markets(markets)[: max(1, int(limit))]
    return {
        "topic": topic_key,
        "queries": terms,
        "status": status,
        "markets": selected,
        "count": len(selected),
        "source": "kalshi_public_api",
    }


def get_kalshi_stock_context(
    symbol: str,
    *,
    company_name: str = "",
    status: str = "open",
    limit: int = 20,
    max_pages_per_query: int = 2,
) -> dict[str, Any]:
    symbol_up = str(symbol or "").upper().strip()
    if not symbol_up:
        raise ValueError("symbol is required.")

    queries = [symbol_up]
    if company_name:
        queries.append(company_name)
    queries.extend(STOCK_CONTEXT_TERMS.get(symbol_up, []))
    queries.extend(["stock market", "Fed", "inflation"])

    markets: list[dict[str, Any]] = []
    for query in _dedupe_strings(queries):
        result = search_kalshi_markets(query, status=status, limit=limit, max_pages=max_pages_per_query)
        markets.extend(result.get("markets", []))
        if len(_dedupe_markets(markets)) >= limit:
            break

    selected = _dedupe_markets(markets)[: max(1, int(limit))]
    return {
        "symbol": symbol_up,
        "company_name": company_name or None,
        "queries": _dedupe_strings(queries),
        "status": status,
        "markets": selected,
        "count": len(selected),
        "source": "kalshi_public_api",
    }


def _dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        cleaned = str(value or "").strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def summarize_markets(markets: list[dict[str, Any]], *, header: str) -> str:
    lines = [header]
    if not markets:
        lines.append("No matching Kalshi markets found.")
        return "\n".join(lines)

    for market in markets[:8]:
        yes = market.get("yes_ask")
        bid = market.get("yes_bid")
        price = f"yes {bid}/{yes}c" if bid is not None or yes is not None else "price N/A"
        volume = market.get("volume")
        lines.append(
            f"- {market.get('ticker')}: {market.get('title')} | {price} | "
            f"vol={volume} | status={market.get('status')}"
        )
    return "\n".join(lines)
