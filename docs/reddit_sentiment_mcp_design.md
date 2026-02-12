# Reddit Sentiment MCP Design

## Goal
Add Reddit-aware MCP tools so the trading agent can consume social signal as one input to decision making.

Important constraint: Reddit signal is noisy and manipulable. It should be treated as a feature, not an execution trigger by itself.

## Design Principles
- Keep tool outputs machine-friendly (`dict`) with a human fallback (`result_text`) to match existing server patterns.
- Separate raw data tools from derived signal tools.
- Include confidence/quality metadata so the LLM can reason about uncertainty.
- Add hard safety gates so sentiment cannot directly place trades.

## Recommended New Modules
- `reddit_data.py`: Reddit API client + query helpers + normalization.
- `reddit_sentiment.py`: ticker extraction, sentiment scoring, confidence scoring.
- `server.py`: MCP tool wrappers.

## Dependencies
- `praw` (or `asyncpraw` if you want async later)
- existing `requests`/`datetime`/`re`

Suggested env vars:
- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `REDDIT_USER_AGENT` (set a stable descriptive string)

## MCP Endpoints

### 1) `get_reddit_posts`
Fetch recent posts for a query and/or set of subreddits.

Arguments:
- `query: str` (e.g. "AAPL OR Apple")
- `subreddits: str = "wallstreetbets,stocks,investing,SecurityAnalysis"`
- `sort: str = "new"` (`new|hot|top|relevance`)
- `time_filter: str = "day"` (`hour|day|week|month|year|all`)
- `limit: int = 50` (cap at 200)

Returns:
- `posts`: list with `id,title,selftext,subreddit,author,score,num_comments,created_utc,url,permalink,upvote_ratio`
- `meta`: `query,subreddits,sort,time_filter,limit,fetched_at_utc`
- `result_text`

### 2) `get_reddit_post_comments`
Fetch top comments for a post.

Arguments:
- `post_id: str`
- `sort: str = "top"`
- `limit: int = 100`

Returns:
- `comments`: list with `id,body,author,score,created_utc,is_submitter`
- `meta`: `post_id,sort,limit,fetched_at_utc`
- `result_text`

### 3) `get_reddit_symbol_mentions`
Extract ticker mention counts and context from posts/comments.

Arguments:
- `symbols: str` (comma separated, e.g. `AAPL,TSLA,NVDA`)
- `subreddits: str = "wallstreetbets,stocks,investing"`
- `lookback_hours: int = 24`
- `include_comments: bool = true`
- `limit_posts: int = 100`

Returns:
- `window`: `{start_utc,end_utc,lookback_hours}`
- `symbols`: list of:
  - `symbol`
  - `mention_count_total`
  - `mention_count_posts`
  - `mention_count_comments`
  - `unique_authors`
  - `avg_post_score`
  - `avg_comment_score`
  - `sample_context` (short snippets, capped)
- `data_quality`: `{posts_scanned,comments_scanned,subreddits,api_latency_ms}`
- `result_text`

### 4) `get_reddit_sentiment_snapshot`
Produce a normalized sentiment factor per symbol.

Arguments:
- `symbols: str`
- `subreddits: str = "wallstreetbets,stocks,investing,SecurityAnalysis"`
- `lookback_hours: int = 24`
- `baseline_days: int = 30` (for z-score vs historical mentions)
- `limit_posts: int = 200`

Returns:
- `window`
- `symbols`: list of:
  - `symbol`
  - `sentiment_score` (range `-1.0..+1.0`)
  - `mention_burst_z` (current mentions vs baseline)
  - `bullish_ratio`
  - `bearish_ratio`
  - `hype_risk` (`low|medium|high`)
  - `confidence` (`0..1`)
  - `components`:
    - `text_polarity`
    - `engagement_weight`
    - `author_diversity`
    - `subreddit_quality_weight`
- `method`: scoring version string (e.g. `reddit_v1`)
- `result_text`

### 5) `get_reddit_trending_tickers` (optional but useful)
Find fast-rising tickers without a predefined symbol list.

Arguments:
- `subreddits: str`
- `lookback_hours: int = 24`
- `min_mentions: int = 15`
- `limit: int = 20`

Returns:
- `trending`: list with `symbol,mentions,mention_burst_z,sentiment_score,confidence`
- `result_text`

## Scoring Model (V1)
Use a simple transparent formula first:

1. Text polarity:
- Lexicon-based bullish/bearish phrase counts (fast, controllable).
- Optional later: FinBERT classifier.

2. Engagement weighting:
- Weight text units by `log(1 + score + num_comments)` for posts.
- Weight comments by `log(1 + score)`.

3. Author diversity penalty:
- Down-weight if a small number of authors dominate mentions.

4. Subreddit quality weight:
- Example: `SecurityAnalysis=1.2`, `stocks=1.0`, `investing=1.0`, `wallstreetbets=0.8`.

5. Final:
- `sentiment_score = clamp(weighted_polarity, -1, 1)`
- `confidence = clamp(data_volume_factor * diversity_factor * source_quality_factor, 0, 1)`

## Anti-Manipulation Controls
- Ignore deleted/removed bodies and very short low-signal texts.
- Penalize repeated near-duplicate posts/comments.
- Cap per-author contribution per symbol per window.
- Require minimum breadth (`unique_authors`, `distinct_subreddits`) before high confidence.
- Persist raw snapshots for audit/replay.

## Trading-Safety Integration (Critical)
Do not let sentiment endpoint outputs directly call `execute_order`.

Recommended policy layer in agent:
- Rule 1: sentiment can only adjust conviction/position size, never bypass risk limits.
- Rule 2: require confirmation from price/volume regime tools (`get_yf_stock_quote`, `get_stock_history`, `get_market_session`).
- Rule 3: block entries during high hype + low confidence combinations.
- Rule 4: enforce per-symbol and daily max loss/turnover caps.

## Suggested Output Contract Example
```json
{
  "window": {"start_utc":"2026-02-08T15:00:00Z","end_utc":"2026-02-09T15:00:00Z","lookback_hours":24},
  "symbols": [
    {
      "symbol":"NVDA",
      "sentiment_score":0.42,
      "mention_burst_z":1.9,
      "bullish_ratio":0.63,
      "bearish_ratio":0.21,
      "hype_risk":"medium",
      "confidence":0.74,
      "components":{
        "text_polarity":0.38,
        "engagement_weight":0.67,
        "author_diversity":0.71,
        "subreddit_quality_weight":0.93
      }
    }
  ],
  "method":"reddit_v1",
  "result_text":"NVDA sentiment +0.42, burst z=1.9, confidence 0.74 (24h)."
}
```

## Implementation Order
1. Add `get_reddit_posts` and `get_reddit_post_comments` (raw ingestion).
2. Add `get_reddit_symbol_mentions` (entity extraction + counts).
3. Add `get_reddit_sentiment_snapshot` (derived factor + confidence).
4. Add caching (5-15 min TTL) and baseline store.
5. Update skill schema/docs and agent prompt policy.

## Validation
- Unit tests:
  - ticker extraction edge cases (`$AAPL`, `AAPL`, false positives like `IT`, `DD`).
  - sentiment polarity phrase tests.
  - confidence penalties under spam-like distributions.
- Backtest sanity checks:
  - Ensure adding sentiment improves risk-adjusted metrics, not just raw return.
  - Test with and without WSB to quantify noise impact.

