"""Reddit mention and sentiment helpers for MCP tools."""
from __future__ import annotations

import math
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, List, Tuple

from reddit_data import fetch_reddit_post_comments, fetch_reddit_posts


BULLISH_TERMS = {
    "buy",
    "long",
    "bull",
    "bullish",
    "breakout",
    "beat",
    "beats",
    "undervalued",
    "moon",
    "rocket",
    "squeeze",
    "upside",
    "upgrade",
    "strong",
}

BEARISH_TERMS = {
    "sell",
    "short",
    "bear",
    "bearish",
    "dump",
    "miss",
    "misses",
    "overvalued",
    "downside",
    "downgrade",
    "weak",
    "fraud",
    "bagholder",
}

COMMON_UPPERCASE_WORDS = {
    "A",
    "AI",
    "ALL",
    "AND",
    "ARE",
    "AS",
    "AT",
    "BE",
    "CEO",
    "CFO",
    "DD",
    "ELI",
    "ETF",
    "FOR",
    "FROM",
    "GDP",
    "GO",
    "HOLD",
    "I",
    "IMO",
    "IN",
    "IPO",
    "IT",
    "LOL",
    "MOON",
    "OR",
    "RSI",
    "SEC",
    "SO",
    "TA",
    "THE",
    "TO",
    "USA",
    "WTF",
    "YOLO",
}

NON_TICKER_FINANCE_TERMS = {
    "ATH",
    "ARPU",
    "CAGR",
    "CPA",
    "CPU",
    "DAU",
    "EBIT",
    "EBITDA",
    "EPS",
    "ETF",
    "EU",
    "FCF",
    "GDP",
    "GMV",
    "IRA",
    "LLM",
    "MAU",
    "PE",
    "PEG",
    "PS",
    "RND",
    "ROE",
    "ROI",
    "RSU",
    "SBC",
    "SOTP",
    "TAM",
    "US",
    "YOY",
}

SUBREDDIT_QUALITY = {
    "securityanalysis": 1.2,
    "stocks": 1.0,
    "investing": 1.0,
    "wallstreetbets": 0.8,
}


def _parse_symbols(symbols: str) -> List[str]:
    parsed = []
    for token in str(symbols or "").split(","):
        sym = token.strip().upper().lstrip("$")
        if sym and re.fullmatch(r"[A-Z]{1,6}", sym):
            parsed.append(sym)
    return sorted(set(parsed))


def _lookback_to_time_filter(lookback_hours: int) -> str:
    if lookback_hours <= 1:
        return "hour"
    if lookback_hours <= 24:
        return "day"
    if lookback_hours <= 24 * 7:
        return "week"
    if lookback_hours <= 24 * 31:
        return "month"
    return "year"


def _make_symbol_query(symbols: List[str]) -> str:
    parts = []
    for sym in symbols:
        parts.append(sym)
        parts.append(f"${sym}")
    return " OR ".join(parts)


def _snippet(text: str, max_len: int = 160) -> str:
    clean = " ".join((text or "").split())
    return clean[:max_len]


def _text_polarity(text: str) -> float:
    words = re.findall(r"[A-Za-z']+", str(text or "").lower())
    if not words:
        return 0.0
    bull = sum(1 for w in words if w in BULLISH_TERMS)
    bear = sum(1 for w in words if w in BEARISH_TERMS)
    return (bull - bear) / float(bull + bear + 1)


def _extract_known_symbol_mentions(text: str, symbols: List[str]) -> List[str]:
    found = []
    source = str(text or "")
    for sym in symbols:
        # Match "$AAPL" or standalone "AAPL"
        if re.search(rf"(?<![A-Z0-9])\$?{re.escape(sym)}(?![A-Z0-9])", source, flags=re.IGNORECASE):
            found.append(sym)
    return found


def _extract_any_ticker_tokens(text: str) -> List[str]:
    found = set()
    for raw in re.findall(r"(?<![A-Z0-9])\$?([A-Z]{1,5})(?![A-Z0-9])", str(text or "")):
        sym = raw.upper()
        if sym in COMMON_UPPERCASE_WORDS:
            continue
        if sym in NON_TICKER_FINANCE_TERMS:
            continue
        if len(sym) == 1:
            continue
        found.add(sym)
    return sorted(found)


def _extract_any_ticker_mentions(text: str) -> Dict[str, Dict[str, int]]:
    source = str(text or "")
    stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"plain": 0, "dollar": 0})

    for raw in re.findall(r"(?<![A-Z0-9])\$([A-Z]{1,5})(?![A-Z0-9])", source):
        sym = raw.upper()
        if sym in COMMON_UPPERCASE_WORDS or sym in NON_TICKER_FINANCE_TERMS or len(sym) == 1:
            continue
        stats[sym]["dollar"] += 1

    for raw in re.findall(r"(?<![\$A-Z0-9])([A-Z]{1,5})(?![A-Z0-9])", source):
        sym = raw.upper()
        if sym in COMMON_UPPERCASE_WORDS or sym in NON_TICKER_FINANCE_TERMS or len(sym) == 1:
            continue
        stats[sym]["plain"] += 1

    return dict(stats)


@lru_cache(maxsize=1024)
def _is_likely_tradable_symbol(symbol: str) -> bool:
    sym = str(symbol or "").upper().strip()
    if not re.fullmatch(r"[A-Z]{1,5}", sym):
        return False
    if sym in COMMON_UPPERCASE_WORDS or sym in NON_TICKER_FINANCE_TERMS:
        return False
    try:
        import yfinance as yf
        info = yf.Ticker(sym).fast_info
        if not info:
            return False
        # Presence of one of these fields is a practical signal that symbol resolves.
        has_price = info.get("last_price") is not None
        has_prev = info.get("previous_close") is not None
        has_open = info.get("open") is not None
        return bool(has_price or has_prev or has_open)
    except Exception:
        return False


def _new_symbol_stats() -> Dict[str, Any]:
    return {
        "mention_count_total": 0,
        "mention_count_posts": 0,
        "mention_count_comments": 0,
        "unique_authors": set(),
        "post_score_sum": 0.0,
        "post_score_n": 0,
        "comment_score_sum": 0.0,
        "comment_score_n": 0,
        "sample_context": [],
        "weighted_polarity_sum": 0.0,
        "polarity_weight_sum": 0.0,
        "bullish_hits": 0,
        "bearish_hits": 0,
        "subreddit_mentions": defaultdict(int),
    }


def _collect_symbol_stats(
    symbols: List[str],
    subreddits: str,
    lookback_hours: int,
    include_comments: bool,
    limit_posts: int,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    t0 = time.time()
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=max(1, int(lookback_hours)))
    query = _make_symbol_query(symbols)
    time_filter = _lookback_to_time_filter(lookback_hours)
    posts_payload = fetch_reddit_posts(
        query=query,
        subreddits=subreddits,
        sort="new",
        time_filter=time_filter,
        limit=max(1, min(int(limit_posts), 200)),
    )

    stats: Dict[str, Dict[str, Any]] = {sym: _new_symbol_stats() for sym in symbols}
    posts_scanned = 0
    comments_scanned = 0

    for post in posts_payload.get("posts", []):
        created = post.get("created_utc")
        if created is None:
            continue
        post_dt = datetime.fromtimestamp(float(created), tz=timezone.utc)
        if post_dt < start or post_dt > now:
            continue

        posts_scanned += 1
        post_text = f"{post.get('title', '')}\n{post.get('selftext', '')}"
        post_mentions = _extract_known_symbol_mentions(post_text, symbols)
        score = int(post.get("score", 0) or 0)
        num_comments = int(post.get("num_comments", 0) or 0)
        author = str(post.get("author", "") or "")
        subreddit = str(post.get("subreddit", "") or "").lower()
        post_polarity = _text_polarity(post_text)
        post_weight = math.log1p(max(0, score) + max(0, num_comments))

        for sym in post_mentions:
            sym_stats = stats[sym]
            sym_stats["mention_count_total"] += 1
            sym_stats["mention_count_posts"] += 1
            if author:
                sym_stats["unique_authors"].add(author)
            sym_stats["post_score_sum"] += score
            sym_stats["post_score_n"] += 1
            if len(sym_stats["sample_context"]) < 3:
                sym_stats["sample_context"].append(_snippet(post_text))
            sym_stats["weighted_polarity_sum"] += post_polarity * post_weight
            sym_stats["polarity_weight_sum"] += post_weight
            if post_polarity > 0:
                sym_stats["bullish_hits"] += 1
            elif post_polarity < 0:
                sym_stats["bearish_hits"] += 1
            sym_stats["subreddit_mentions"][subreddit] += 1

        if include_comments and post_mentions:
            comments_payload = fetch_reddit_post_comments(
                post_id=str(post.get("id")),
                sort="top",
                limit=40,
            )
            for c in comments_payload.get("comments", []):
                comments_scanned += 1
                body = c.get("body", "") or ""
                comment_mentions = _extract_known_symbol_mentions(body, symbols)
                if not comment_mentions:
                    continue
                c_score = int(c.get("score", 0) or 0)
                c_author = str(c.get("author", "") or "")
                c_polarity = _text_polarity(body)
                c_weight = math.log1p(max(0, c_score))

                for sym in comment_mentions:
                    sym_stats = stats[sym]
                    sym_stats["mention_count_total"] += 1
                    sym_stats["mention_count_comments"] += 1
                    if c_author:
                        sym_stats["unique_authors"].add(c_author)
                    sym_stats["comment_score_sum"] += c_score
                    sym_stats["comment_score_n"] += 1
                    if len(sym_stats["sample_context"]) < 3:
                        sym_stats["sample_context"].append(_snippet(body))
                    sym_stats["weighted_polarity_sum"] += c_polarity * c_weight
                    sym_stats["polarity_weight_sum"] += c_weight
                    if c_polarity > 0:
                        sym_stats["bullish_hits"] += 1
                    elif c_polarity < 0:
                        sym_stats["bearish_hits"] += 1
                    sym_stats["subreddit_mentions"][subreddit] += 1

    data_quality = {
        "posts_scanned": posts_scanned,
        "comments_scanned": comments_scanned,
        "subreddits": posts_payload.get("meta", {}).get("subreddits", []),
        "api_latency_ms": int((time.time() - t0) * 1000),
        "query": query,
        "time_filter": time_filter,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return stats, data_quality


def get_reddit_symbol_mentions(
    symbols: str,
    subreddits: str = "wallstreetbets,stocks,investing",
    lookback_hours: int = 24,
    include_comments: bool = True,
    limit_posts: int = 100,
) -> Dict[str, Any]:
    parsed = _parse_symbols(symbols)
    if not parsed:
        raise ValueError("symbols is required (comma-separated tickers).")

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=max(1, int(lookback_hours)))
    stats, data_quality = _collect_symbol_stats(
        symbols=parsed,
        subreddits=subreddits,
        lookback_hours=lookback_hours,
        include_comments=include_comments,
        limit_posts=limit_posts,
    )

    rows = []
    for sym in parsed:
        st = stats[sym]
        avg_post = st["post_score_sum"] / st["post_score_n"] if st["post_score_n"] else 0.0
        avg_comment = st["comment_score_sum"] / st["comment_score_n"] if st["comment_score_n"] else 0.0
        rows.append(
            {
                "symbol": sym,
                "mention_count_total": st["mention_count_total"],
                "mention_count_posts": st["mention_count_posts"],
                "mention_count_comments": st["mention_count_comments"],
                "unique_authors": len(st["unique_authors"]),
                "avg_post_score": round(avg_post, 2),
                "avg_comment_score": round(avg_comment, 2),
                "sample_context": st["sample_context"],
            }
        )

    lines = []
    for r in rows:
        lines.append(
            f"{r['symbol']}: mentions={r['mention_count_total']} "
            f"(posts={r['mention_count_posts']}, comments={r['mention_count_comments']}), "
            f"authors={r['unique_authors']}"
        )
    if not lines:
        lines = ["No symbol mentions found."]

    return {
        "window": {
            "start_utc": start.isoformat(),
            "end_utc": now.isoformat(),
            "lookback_hours": max(1, int(lookback_hours)),
        },
        "symbols": rows,
        "data_quality": data_quality,
        "result_text": "\n".join(lines),
    }


def _baseline_mentions_poisson_z(
    symbol: str,
    current_mentions: int,
    lookback_hours: int,
    subreddits: str,
    baseline_days: int,
    limit_posts: int,
) -> float:
    now = datetime.now(timezone.utc)
    baseline_start = now - timedelta(days=max(1, int(baseline_days)))
    current_window_start = now - timedelta(hours=max(1, int(lookback_hours)))
    tf = "month" if baseline_days <= 31 else "year"
    query = f"{symbol} OR ${symbol}"

    payload = fetch_reddit_posts(
        query=query,
        subreddits=subreddits,
        sort="new",
        time_filter=tf,
        limit=max(50, min(limit_posts * 3, 400)),
    )

    baseline_mentions = 0
    for post in payload.get("posts", []):
        created = post.get("created_utc")
        if created is None:
            continue
        dt = datetime.fromtimestamp(float(created), tz=timezone.utc)
        if not (baseline_start <= dt < current_window_start):
            continue
        text = f"{post.get('title', '')}\n{post.get('selftext', '')}"
        if _extract_known_symbol_mentions(text, [symbol]):
            baseline_mentions += 1

    baseline_hours = max(1.0, float(baseline_days) * 24.0 - float(lookback_hours))
    baseline_rate = baseline_mentions / baseline_hours
    expected = baseline_rate * float(max(1, int(lookback_hours)))
    return (current_mentions - expected) / math.sqrt(max(expected, 1.0))


def get_reddit_sentiment_snapshot(
    symbols: str,
    subreddits: str = "wallstreetbets,stocks,investing,SecurityAnalysis",
    lookback_hours: int = 24,
    baseline_days: int = 30,
    limit_posts: int = 200,
) -> Dict[str, Any]:
    parsed = _parse_symbols(symbols)
    if not parsed:
        raise ValueError("symbols is required (comma-separated tickers).")

    mentions = get_reddit_symbol_mentions(
        symbols=",".join(parsed),
        subreddits=subreddits,
        lookback_hours=lookback_hours,
        include_comments=True,
        limit_posts=limit_posts,
    )
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=max(1, int(lookback_hours)))

    # Build a quick lookup from mention rows.
    mention_rows = {row["symbol"]: row for row in mentions.get("symbols", [])}

    # Recompute detailed stats once to access polarity and subreddit distribution.
    stats, _ = _collect_symbol_stats(
        symbols=parsed,
        subreddits=subreddits,
        lookback_hours=lookback_hours,
        include_comments=True,
        limit_posts=limit_posts,
    )

    out = []
    for sym in parsed:
        st = stats[sym]
        row = mention_rows.get(sym, {})
        total = max(0, int(row.get("mention_count_total", 0)))
        unique_authors = max(0, int(row.get("unique_authors", 0)))
        polarity = (
            st["weighted_polarity_sum"] / st["polarity_weight_sum"]
            if st["polarity_weight_sum"] > 0
            else 0.0
        )
        polar_hits = max(1, st["bullish_hits"] + st["bearish_hits"])
        bullish_ratio = st["bullish_hits"] / float(polar_hits)
        bearish_ratio = st["bearish_hits"] / float(polar_hits)

        # Quality weighting by subreddit source mix.
        sr_total = sum(st["subreddit_mentions"].values()) or 1
        quality_weight = 0.0
        for sr, c in st["subreddit_mentions"].items():
            quality_weight += (c / sr_total) * SUBREDDIT_QUALITY.get(sr, 0.9)
        quality_weight = quality_weight or 0.9

        burst_z = _baseline_mentions_poisson_z(
            symbol=sym,
            current_mentions=total,
            lookback_hours=lookback_hours,
            subreddits=subreddits,
            baseline_days=baseline_days,
            limit_posts=limit_posts,
        )

        volume_factor = min(1.0, total / 30.0)
        diversity_factor = min(1.0, unique_authors / max(1.0, total * 0.7))
        source_quality_factor = min(1.0, max(0.4, quality_weight))
        confidence = max(0.0, min(1.0, volume_factor * diversity_factor * source_quality_factor))
        sentiment_score = max(-1.0, min(1.0, polarity * quality_weight))

        if burst_z >= 2.0 and confidence < 0.45:
            hype_risk = "high"
        elif burst_z >= 1.0:
            hype_risk = "medium"
        else:
            hype_risk = "low"

        out.append(
            {
                "symbol": sym,
                "sentiment_score": round(sentiment_score, 4),
                "mention_burst_z": round(burst_z, 3),
                "bullish_ratio": round(bullish_ratio, 3),
                "bearish_ratio": round(bearish_ratio, 3),
                "hype_risk": hype_risk,
                "confidence": round(confidence, 3),
                "components": {
                    "text_polarity": round(polarity, 4),
                    "engagement_weight": round(min(1.0, math.log1p(total) / 4.0), 3),
                    "author_diversity": round(diversity_factor, 3),
                    "subreddit_quality_weight": round(quality_weight, 3),
                },
            }
        )

    lines = []
    for item in out:
        lines.append(
            f"{item['symbol']}: sentiment={item['sentiment_score']:+.2f}, "
            f"burst_z={item['mention_burst_z']:+.2f}, confidence={item['confidence']:.2f}, "
            f"hype={item['hype_risk']}"
        )
    if not lines:
        lines = ["No sentiment snapshot available."]

    return {
        "window": {
            "start_utc": start.isoformat(),
            "end_utc": now.isoformat(),
            "lookback_hours": max(1, int(lookback_hours)),
        },
        "symbols": out,
        "method": "reddit_v1",
        "result_text": "\n".join(lines),
    }


def get_reddit_trending_tickers(
    subreddits: str = "wallstreetbets,stocks,investing",
    lookback_hours: int = 24,
    min_mentions: int = 15,
    limit: int = 20,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=max(1, int(lookback_hours)))
    payload = fetch_reddit_posts(
        query="stock OR earnings OR calls OR puts OR guidance",
        subreddits=subreddits,
        sort="new",
        time_filter=_lookback_to_time_filter(lookback_hours),
        limit=200,
    )

    mention_counts = defaultdict(int)
    mention_dollar_counts = defaultdict(int)
    unique_authors = defaultdict(set)
    polarity_sums = defaultdict(float)
    polarity_n = defaultdict(int)

    posts_considered = 0
    for post in payload.get("posts", []):
        created = post.get("created_utc")
        if created is None:
            continue
        dt = datetime.fromtimestamp(float(created), tz=timezone.utc)
        if dt < start or dt > now:
            continue

        posts_considered += 1
        text = f"{post.get('title', '')}\n{post.get('selftext', '')}"
        mentions = _extract_any_ticker_mentions(text)
        if not mentions:
            continue
        pol = _text_polarity(text)
        author = str(post.get("author", "") or "")
        for sym, ms in mentions.items():
            sym_mentions = int(ms.get("plain", 0)) + int(ms.get("dollar", 0))
            if sym_mentions <= 0:
                continue
            mention_counts[sym] += sym_mentions
            mention_dollar_counts[sym] += int(ms.get("dollar", 0))
            if author:
                unique_authors[sym].add(author)
            polarity_sums[sym] += pol
            polarity_n[sym] += 1

    rows = []
    safe_min_mentions = max(1, int(min_mentions))
    for sym, count in mention_counts.items():
        if count < safe_min_mentions:
            continue
        authors_n = len(unique_authors[sym])
        # Keep plain-uppercase detections only if there is breadth; otherwise require $TICKER usage.
        if mention_dollar_counts[sym] == 0 and authors_n < 2:
            continue
        if not _is_likely_tradable_symbol(sym):
            continue
        pol = polarity_sums[sym] / max(1, polarity_n[sym])
        conf = min(1.0, (count / 40.0) * min(1.0, authors_n / max(1.0, count * 0.7)))
        rows.append(
            {
                "symbol": sym,
                "mentions": int(count),
                "dollar_mentions": int(mention_dollar_counts[sym]),
                "unique_authors": int(authors_n),
                "mention_burst_z": round((count - safe_min_mentions) / math.sqrt(max(1, safe_min_mentions)), 3),
                "sentiment_score": round(max(-1.0, min(1.0, pol)), 4),
                "confidence": round(max(0.0, min(1.0, conf)), 3),
            }
        )

    rows.sort(key=lambda x: (x["mentions"], abs(x["sentiment_score"])), reverse=True)
    rows = rows[: max(1, min(int(limit), 50))]

    lines = [
        f"{r['symbol']}: mentions={r['mentions']} ($={r['dollar_mentions']}), "
        f"authors={r['unique_authors']}, sentiment={r['sentiment_score']:+.2f}"
        for r in rows
    ]
    if not lines:
        lines = ["No trending tickers found for the specified window."]

    return {
        "window": {
            "start_utc": start.isoformat(),
            "end_utc": now.isoformat(),
            "lookback_hours": max(1, int(lookback_hours)),
        },
        "trending": rows,
        "data_quality": {
            "posts_scanned": posts_considered,
            "subreddits": payload.get("meta", {}).get("subreddits", []),
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "result_text": "\n".join(lines),
    }
