"""Reddit-related MCP tool registrations."""
from __future__ import annotations

from reddit_data import fetch_reddit_post_comments, fetch_reddit_posts
from reddit_sentiment import (
    get_reddit_sentiment_snapshot as build_reddit_sentiment_snapshot,
    get_reddit_symbol_mentions as build_reddit_symbol_mentions,
    get_reddit_trending_tickers as build_reddit_trending_tickers,
)


def register_reddit_tools(mcp) -> None:
    @mcp.tool()
    def get_reddit_posts(
        query: str,
        subreddits: str = "wallstreetbets,stocks,investing,SecurityAnalysis",
        sort: str = "new",
        time_filter: str = "day",
        limit: int = 50,
    ) -> dict:
        """Fetch recent Reddit posts for a query across one or more subreddits."""
        try:
            payload = fetch_reddit_posts(
                query=query,
                subreddits=subreddits,
                sort=sort,
                time_filter=time_filter,
                limit=limit,
            )
            posts = payload.get("posts", [])
            lines = [f"Fetched {len(posts)} Reddit posts for query: {query}"]
            for post in posts[:5]:
                lines.append(
                    f"- [{post.get('subreddit')}] {post.get('title')} "
                    f"(score={post.get('score')}, comments={post.get('num_comments')})"
                )
            payload["result_text"] = "\n".join(lines)
            return payload
        except Exception as e:
            return {
                "posts": [],
                "meta": {
                    "query": query,
                    "subreddits": [s.strip() for s in str(subreddits).split(",") if s.strip()],
                    "sort": sort,
                    "time_filter": time_filter,
                    "limit": limit,
                },
                "error": str(e),
                "result_text": f"Error fetching Reddit posts: {str(e)}",
            }

    @mcp.tool()
    def get_reddit_post_comments(post_id: str, sort: str = "top", limit: int = 100) -> dict:
        """Fetch comments for a Reddit post by post id."""
        try:
            payload = fetch_reddit_post_comments(post_id=post_id, sort=sort, limit=limit)
            comments = payload.get("comments", [])
            lines = [f"Fetched {len(comments)} comments for post {post_id}."]
            for comment in comments[:5]:
                lines.append(f"- score={comment.get('score')}: {(comment.get('body') or '')[:120]}")
            payload["result_text"] = "\n".join(lines)
            return payload
        except Exception as e:
            return {
                "comments": [],
                "meta": {"post_id": post_id, "sort": sort, "limit": limit},
                "error": str(e),
                "result_text": f"Error fetching Reddit comments: {str(e)}",
            }

    @mcp.tool()
    def get_reddit_symbol_mentions(
        symbols: str,
        subreddits: str = "wallstreetbets,stocks,investing",
        lookback_hours: int = 24,
        include_comments: bool = True,
        limit_posts: int = 100,
    ) -> dict:
        """Extract ticker mention counts and context from Reddit posts/comments."""
        try:
            return build_reddit_symbol_mentions(
                symbols=symbols,
                subreddits=subreddits,
                lookback_hours=lookback_hours,
                include_comments=include_comments,
                limit_posts=limit_posts,
            )
        except Exception as e:
            return {
                "window": {},
                "symbols": [],
                "data_quality": {},
                "error": str(e),
                "result_text": f"Error computing Reddit symbol mentions: {str(e)}",
            }

    @mcp.tool()
    def get_reddit_sentiment_snapshot(
        symbols: str,
        subreddits: str = "wallstreetbets,stocks,investing,SecurityAnalysis",
        lookback_hours: int = 24,
        baseline_days: int = 30,
        limit_posts: int = 200,
    ) -> dict:
        """Compute a normalized Reddit sentiment factor per symbol."""
        try:
            return build_reddit_sentiment_snapshot(
                symbols=symbols,
                subreddits=subreddits,
                lookback_hours=lookback_hours,
                baseline_days=baseline_days,
                limit_posts=limit_posts,
            )
        except Exception as e:
            return {
                "window": {},
                "symbols": [],
                "method": "reddit_v1",
                "error": str(e),
                "result_text": f"Error computing Reddit sentiment snapshot: {str(e)}",
            }

    @mcp.tool()
    def get_reddit_ticker_sentiment(
        tickers: str,
        subreddits: str = "wallstreetbets,stocks,investing,SecurityAnalysis",
        lookback_hours: int = 24,
        baseline_days: int = 30,
        limit_posts: int = 200,
    ) -> dict:
        """Compute Reddit sentiment for a manual comma-separated ticker list."""
        try:
            return build_reddit_sentiment_snapshot(
                symbols=tickers,
                subreddits=subreddits,
                lookback_hours=lookback_hours,
                baseline_days=baseline_days,
                limit_posts=limit_posts,
            )
        except Exception as e:
            return {
                "window": {},
                "symbols": [],
                "method": "reddit_v1",
                "error": str(e),
                "result_text": f"Error computing Reddit ticker sentiment: {str(e)}",
            }

    @mcp.tool()
    def get_reddit_trending_tickers(
        subreddits: str = "wallstreetbets,stocks,investing",
        lookback_hours: int = 24,
        min_mentions: int = 15,
        limit: int = 20,
    ) -> dict:
        """Find fast-rising ticker mentions on Reddit."""
        try:
            return build_reddit_trending_tickers(
                subreddits=subreddits,
                lookback_hours=lookback_hours,
                min_mentions=min_mentions,
                limit=limit,
            )
        except Exception as e:
            return {
                "window": {},
                "trending": [],
                "data_quality": {},
                "error": str(e),
                "result_text": f"Error computing Reddit trending tickers: {str(e)}",
            }

