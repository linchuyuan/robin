"""
News sentiment pipeline: yfinance news + lightweight VADER-like lexicon, with
publication-tier weighting. Combines with Reddit sentiment when available.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

import yfinance as yf

from yahoo_finance import get_yf_news


# Tier 1 = highest-quality financial press; Tier 3 = aggregators/blogs.
PUBLISHER_TIERS = {
    "Bloomberg": 1.0, "Reuters": 1.0, "Wall Street Journal": 1.0, "Financial Times": 1.0,
    "WSJ": 1.0, "Barron's": 0.95, "CNBC": 0.85, "MarketWatch": 0.8, "Forbes": 0.7,
    "Seeking Alpha": 0.6, "Motley Fool": 0.5, "Benzinga": 0.5, "Zacks": 0.55,
    "Yahoo Finance": 0.6, "Investor's Business Daily": 0.75, "TheStreet": 0.55,
}
DEFAULT_TIER = 0.5


# Simplified sentiment lexicon. Real VADER has more nuance; this is a
# lightweight, dependency-free approximation tuned for financial headlines.
POSITIVE_TERMS = {
    "beat", "beats", "tops", "exceed", "exceeded", "rise", "rises", "rising",
    "surge", "surges", "soar", "soars", "jump", "jumps", "gain", "gains",
    "boost", "boosts", "upgrade", "upgraded", "outperform", "outperforms",
    "raises", "raise", "guidance", "strong", "record", "bullish",
    "accelerate", "accelerates", "rally", "rallies", "breakthrough", "positive",
    "expansion", "expanding", "growth", "growing", "profit", "profits",
    "momentum", "leading", "wins", "won", "secured", "approve", "approved",
    "launch", "launched", "partnership", "acquisition",
}

NEGATIVE_TERMS = {
    "miss", "misses", "missed", "disappoint", "disappoints", "fall", "falls",
    "falling", "drop", "drops", "dropped", "plunge", "plunges", "slide",
    "slides", "decline", "declines", "declining", "weak", "weakness",
    "downgrade", "downgraded", "underperform", "underperforms", "cut", "cuts",
    "lower", "lowered", "warn", "warns", "warned", "warning", "bearish",
    "loss", "losses", "recession", "slowdown", "selloff", "crash",
    "investigation", "lawsuit", "fraud", "restate", "restatement",
    "layoff", "layoffs", "bankruptcy", "delay", "delayed", "downturn",
    "crisis", "struggle", "struggling", "concern", "concerns", "risk",
}


def _publisher_weight(publisher: str) -> float:
    if not publisher:
        return DEFAULT_TIER
    for key, weight in PUBLISHER_TIERS.items():
        if key.lower() in publisher.lower():
            return weight
    return DEFAULT_TIER


def _score_text(text: str) -> tuple[float, int, int]:
    """Return (polarity in [-1, 1], positive_hits, negative_hits)."""
    if not text:
        return 0.0, 0, 0
    tokens = text.lower().replace("-", " ").split()
    pos = sum(1 for t in tokens if t.strip(".,:;!?\"'()") in POSITIVE_TERMS)
    neg = sum(1 for t in tokens if t.strip(".,:;!?\"'()") in NEGATIVE_TERMS)
    total = pos + neg
    if total == 0:
        return 0.0, 0, 0
    return (pos - neg) / total, pos, neg


def _time_decay(hours_old: float, half_life_hours: float = 36) -> float:
    """Exponential decay; 36h half-life by default."""
    if hours_old < 0:
        return 1.0
    return 0.5 ** (hours_old / half_life_hours)


def get_news_sentiment(symbol: str, lookback_hours: int = 72) -> dict:
    """
    Compute a weighted news sentiment score for a symbol.

    Returns:
        {
          "symbol": str,
          "sentiment_score": float in [-1, 1],
          "article_count": int,
          "weighted_article_count": float,
          "top_articles": [...],  # with polarity
        }
    """
    sym = str(symbol).upper().strip()
    try:
        articles = get_yf_news(sym) or []
    except Exception as e:
        return {"symbol": sym, "error": str(e), "sentiment_score": 0.0, "article_count": 0}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max(1, int(lookback_hours)))

    scored = []
    total_weighted_polarity = 0.0
    total_weight = 0.0

    for art in articles:
        title = art.get("title") or ""
        summary = art.get("summary") or art.get("description") or ""
        publisher = art.get("publisher") or art.get("source") or ""
        ts = art.get("providerPublishTime") or art.get("published_at") or art.get("pub_date")

        # Parse timestamp
        art_time = None
        if isinstance(ts, (int, float)):
            try:
                art_time = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            except Exception:
                art_time = None
        elif isinstance(ts, str):
            try:
                art_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                art_time = None
        if art_time is None:
            art_time = now  # fallback; treat as fresh

        if art_time < cutoff:
            continue

        combined_text = f"{title}. {summary}"
        polarity, pos_hits, neg_hits = _score_text(combined_text)
        if pos_hits + neg_hits == 0:
            continue  # no sentiment signal in this article

        hours_old = (now - art_time).total_seconds() / 3600
        pub_weight = _publisher_weight(publisher)
        decay = _time_decay(hours_old)
        weight = pub_weight * decay

        total_weighted_polarity += polarity * weight
        total_weight += weight

        scored.append({
            "title": title[:150],
            "publisher": publisher,
            "hours_old": round(hours_old, 1),
            "polarity": round(polarity, 3),
            "weight": round(weight, 3),
        })

    sentiment_score = total_weighted_polarity / total_weight if total_weight > 0 else 0.0

    scored.sort(key=lambda x: abs(x["polarity"]) * x["weight"], reverse=True)

    return {
        "symbol": sym,
        "sentiment_score": round(sentiment_score, 4),
        "article_count": len(scored),
        "weighted_article_count": round(total_weight, 2),
        "top_articles": scored[:5],
        "lookback_hours": lookback_hours,
        "computed_at_utc": now.isoformat().replace("+00:00", "Z"),
    }


def combine_sentiment_sources(
    reddit_score: float | None,
    reddit_confidence: float | None,
    news_score: float | None,
    news_weighted_count: float | None,
) -> dict:
    """
    Combine Reddit and news sentiment with confidence-weighted averaging.

    Returns a unified score with source breakdown.
    """
    sources = []
    total_score = 0.0
    total_weight = 0.0

    if reddit_score is not None:
        r_conf = max(0.0, float(reddit_confidence or 0.0))
        sources.append({"source": "reddit", "score": reddit_score, "weight": r_conf})
        total_score += reddit_score * r_conf
        total_weight += r_conf

    if news_score is not None:
        # News weight: log-scaled by article count, capped at 1.0
        import math
        n_weight = min(1.0, math.log1p(max(0.0, float(news_weighted_count or 0.0))) / 3.0)
        sources.append({"source": "news", "score": news_score, "weight": n_weight})
        total_score += news_score * n_weight
        total_weight += n_weight

    combined = total_score / total_weight if total_weight > 0 else 0.0
    return {
        "combined_score": round(combined, 4),
        "total_weight": round(total_weight, 3),
        "sources": sources,
    }
