"""Economic event calendar helpers for macro scheduling context."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile
from typing import Any

import requests

FOREX_FACTORY_WEEK_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
IMPACT_RANK = {"holiday": 0, "low": 1, "medium": 2, "high": 3}
DEFAULT_CACHE_TTL_SECONDS = 3600
DEFAULT_CACHE_PATH = os.path.join(tempfile.gettempdir(), "robin_economic_events_cache.json")


class CalendarRateLimitError(RuntimeError):
    """Raised when the upstream economic calendar feed is rate-limited."""


def _parse_csv(raw: str | None) -> list[str]:
    if raw in (None, ""):
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _get_int_env(name: str, default: int) -> int:
    try:
        raw = os.getenv(name)
        if raw in (None, ""):
            return int(default)
        return max(1, int(float(raw)))
    except Exception:
        return int(default)


def _load_cached_feed(path: str) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as fp:
            payload = json.load(fp)
        if not isinstance(payload, dict):
            return None
        if not isinstance(payload.get("fetched_at"), str):
            return None
        if not isinstance(payload.get("data"), list):
            return None
        return payload
    except Exception:
        return None


def _save_cached_feed(path: str, data: list[dict[str, Any]], fetched_at: datetime) -> None:
    try:
        payload = {
            "fetched_at": fetched_at.isoformat(),
            "data": data,
        }
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=True)
    except Exception:
        # Cache write failures should never break endpoint behavior.
        return


def _is_rate_limit_message(body: str) -> bool:
    text = str(body or "").lower()
    if not text:
        return False
    return (
        "calendar export requests" in text
        or "wait five minutes" in text
        or "only updated once per hour" in text
    )


def _fetch_upstream_feed(url: str, headers: dict[str, str], timeout_seconds: int) -> list[dict[str, Any]]:
    response = requests.get(url, headers=headers, timeout=timeout_seconds)
    body = response.text or ""
    if response.status_code != 200:
        if _is_rate_limit_message(body):
            raise CalendarRateLimitError(body.strip())
        response.raise_for_status()
    if _is_rate_limit_message(body):
        raise CalendarRateLimitError(body.strip())
    data = response.json()
    if not isinstance(data, list):
        raise ValueError("Economic calendar payload is not a list.")
    return data


def get_economic_events_feed(
    *,
    limit: int = 20,
    days_ahead: int = 14,
    countries: str = "USD",
    min_impact: str = "High",
    keywords: str = "",
) -> dict[str, Any]:
    """
    Fetch and filter upcoming economic events.

    Source note: uses ForexFactory's weekly JSON feed.
    """
    url = os.getenv("ROBIN_ECON_CALENDAR_URL", FOREX_FACTORY_WEEK_URL)
    cache_path = os.getenv("ROBIN_ECON_CACHE_PATH", DEFAULT_CACHE_PATH)
    cache_ttl_seconds = _get_int_env("ROBIN_ECON_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS)
    timeout_seconds = _get_int_env("ROBIN_ECON_TIMEOUT_SECONDS", 8)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }

    country_set = {x.upper() for x in _parse_csv(countries)}
    keyword_list = [x.lower() for x in _parse_csv(keywords)]
    min_impact_rank = IMPACT_RANK.get(str(min_impact or "").strip().lower(), 0)

    now_utc = datetime.now(timezone.utc)
    end_utc = now_utc + timedelta(days=max(1, int(days_ahead)))
    cache_payload = _load_cached_feed(cache_path)
    cache_fetched_at = _parse_dt((cache_payload or {}).get("fetched_at"))
    cache_data = (cache_payload or {}).get("data") if cache_payload else None

    data_source = "upstream"
    warning = None
    data: list[dict[str, Any]]

    use_fresh_cache = (
        cache_fetched_at is not None
        and isinstance(cache_data, list)
        and (now_utc - cache_fetched_at).total_seconds() < cache_ttl_seconds
    )
    if use_fresh_cache:
        data = cache_data
        data_source = "cache_fresh"
    else:
        try:
            data = _fetch_upstream_feed(url, headers, timeout_seconds)
            _save_cached_feed(cache_path, data, now_utc)
        except CalendarRateLimitError as rate_limit_error:
            if isinstance(cache_data, list) and cache_data:
                data = cache_data
                data_source = "cache_stale"
                warning = (
                    "Upstream economic calendar rate-limited; served from stale cache. "
                    f"Upstream message: {str(rate_limit_error)}"
                )
            else:
                data = []
                data_source = "upstream_rate_limited"
                warning = (
                    "Upstream economic calendar rate-limited and no cache is available yet. "
                    "Please wait 5-10 minutes and retry; the source updates hourly."
                )
        except Exception:
            if isinstance(cache_data, list) and cache_data:
                data = cache_data
                data_source = "cache_stale"
                warning = "Upstream economic calendar unavailable; served from stale cache."
            else:
                data = []
                data_source = "upstream_unavailable"
                warning = "Upstream economic calendar unavailable and no cache is available yet."

    events: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue

        title = str(row.get("title") or "").strip()
        country = str(row.get("country") or "").strip().upper()
        impact = str(row.get("impact") or "").strip()
        dt = _parse_dt(row.get("date"))
        impact_rank = IMPACT_RANK.get(impact.lower(), 0)

        if not title or not dt:
            continue
        if dt < now_utc or dt > end_utc:
            continue
        if country_set and country not in country_set:
            continue
        if impact_rank < min_impact_rank:
            continue
        if keyword_list:
            title_lc = title.lower()
            if not any(kw in title_lc for kw in keyword_list):
                continue

        events.append(
            {
                "title": title,
                "country": country,
                "datetime": dt.isoformat(),
                "impact": impact,
                "impact_rank": impact_rank,
                "forecast": row.get("forecast"),
                "previous": row.get("previous"),
                "hours_until": round((dt - now_utc).total_seconds() / 3600.0, 2),
            }
        )

    events.sort(key=lambda item: item.get("datetime") or "")
    selected = events[: max(1, int(limit))]

    return {
        "source": "forexfactory_week_feed",
        "source_url": url,
        "source_mode": data_source,
        "cache_path": cache_path,
        "cache_ttl_seconds": cache_ttl_seconds,
        "cache_fetched_at": cache_fetched_at.isoformat() if cache_fetched_at else None,
        "as_of_utc": now_utc.isoformat(),
        "window_end_utc": end_utc.isoformat(),
        "filters": {
            "countries": sorted(country_set),
            "min_impact": str(min_impact or ""),
            "keywords": keyword_list,
            "days_ahead": max(1, int(days_ahead)),
        },
        "events": selected,
        "total_matched": len(events),
        "warning": warning,
    }
