"""Reddit data access helpers for MCP tools."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests


def _iso_utc(ts: float | int | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _parse_subreddits(subreddits: str) -> List[str]:
    subs = [s.strip() for s in str(subreddits or "").split(",") if s.strip()]
    return subs or ["wallstreetbets", "stocks", "investing", "SecurityAnalysis"]


def _get_reddit_client() -> Any:
    try:
        import praw
    except Exception as e:
        raise RuntimeError("praw is not installed. Run: pip install -r requirements.txt") from e

    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    user_agent = os.getenv("REDDIT_USER_AGENT")

    if not client_id or not client_secret or not user_agent:
        raise RuntimeError(
            "Missing Reddit credentials. Set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, and REDDIT_USER_AGENT."
        )

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )
    reddit.read_only = True
    return reddit


def _get_auth_mode() -> str:
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    user_agent = os.getenv("REDDIT_USER_AGENT")
    if client_id and client_secret and user_agent:
        return "oauth"
    return "public"


def _http_headers() -> Dict[str, str]:
    return {
        "User-Agent": os.getenv("REDDIT_USER_AGENT", "robin-mcp-public/1.0"),
        "Accept": "application/json",
    }


def _submission_to_dict(submission: Any) -> Dict[str, Any]:
    return {
        "id": getattr(submission, "id", None),
        "title": getattr(submission, "title", None),
        "selftext": getattr(submission, "selftext", None),
        "subreddit": str(getattr(submission, "subreddit", "")),
        "author": str(getattr(submission, "author", "")),
        "score": int(getattr(submission, "score", 0) or 0),
        "num_comments": int(getattr(submission, "num_comments", 0) or 0),
        "created_utc": getattr(submission, "created_utc", None),
        "created_at": _iso_utc(getattr(submission, "created_utc", None)),
        "url": getattr(submission, "url", None),
        "permalink": f"https://www.reddit.com{getattr(submission, 'permalink', '')}",
        "upvote_ratio": getattr(submission, "upvote_ratio", None),
    }


def _comment_to_dict(comment: Any) -> Dict[str, Any]:
    return {
        "id": getattr(comment, "id", None),
        "body": getattr(comment, "body", None),
        "author": str(getattr(comment, "author", "")),
        "score": int(getattr(comment, "score", 0) or 0),
        "created_utc": getattr(comment, "created_utc", None),
        "created_at": _iso_utc(getattr(comment, "created_utc", None)),
        "is_submitter": bool(getattr(comment, "is_submitter", False)),
    }


def _submission_json_to_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "selftext": data.get("selftext"),
        "subreddit": data.get("subreddit"),
        "author": data.get("author"),
        "score": int(data.get("score", 0) or 0),
        "num_comments": int(data.get("num_comments", 0) or 0),
        "created_utc": data.get("created_utc"),
        "created_at": _iso_utc(data.get("created_utc")),
        "url": data.get("url"),
        "permalink": f"https://www.reddit.com{data.get('permalink', '')}",
        "upvote_ratio": data.get("upvote_ratio"),
    }


def _comment_json_to_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": data.get("id"),
        "body": data.get("body"),
        "author": data.get("author"),
        "score": int(data.get("score", 0) or 0),
        "created_utc": data.get("created_utc"),
        "created_at": _iso_utc(data.get("created_utc")),
        "is_submitter": bool(data.get("is_submitter", False)),
    }


def _flatten_comment_children(children: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for child in children or []:
        if child.get("kind") != "t1":
            continue
        data = child.get("data", {}) or {}
        out.append(_comment_json_to_dict(data))
        replies = data.get("replies")
        if isinstance(replies, dict):
            nested = replies.get("data", {}).get("children", []) or []
            out.extend(_flatten_comment_children(nested))
    return out


def fetch_reddit_posts(
    query: str,
    subreddits: str,
    sort: str = "new",
    time_filter: str = "day",
    limit: int = 50,
) -> Dict[str, Any]:
    subs = _parse_subreddits(subreddits)
    safe_limit = max(1, min(int(limit), 200))
    safe_sort = str(sort or "new").lower()
    safe_time_filter = str(time_filter or "day").lower()
    safe_query = str(query or "").strip()

    if not safe_query:
        raise ValueError("query is required")

    auth_mode = _get_auth_mode()
    posts: List[Dict[str, Any]] = []
    if auth_mode == "oauth":
        reddit = _get_reddit_client()
        sub_expr = "+".join(subs)
        subreddit = reddit.subreddit(sub_expr)
        for submission in subreddit.search(
            query=safe_query,
            sort=safe_sort,
            time_filter=safe_time_filter,
            limit=safe_limit,
        ):
            posts.append(_submission_to_dict(submission))
    else:
        sub_expr = "+".join(subs)
        url = f"https://www.reddit.com/r/{sub_expr}/search.json"
        params = {
            "q": safe_query,
            "sort": safe_sort,
            "t": safe_time_filter,
            "restrict_sr": "on",
            "limit": safe_limit,
        }
        resp = requests.get(url, params=params, headers=_http_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        children = data.get("data", {}).get("children", []) or []
        for child in children:
            if child.get("kind") != "t3":
                continue
            posts.append(_submission_json_to_dict(child.get("data", {}) or {}))

    return {
        "posts": posts,
        "meta": {
            "query": safe_query,
            "subreddits": subs,
            "sort": safe_sort,
            "time_filter": safe_time_filter,
            "limit": safe_limit,
            "auth_mode": auth_mode,
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    }


def fetch_reddit_post_comments(
    post_id: str,
    sort: str = "top",
    limit: int = 100,
) -> Dict[str, Any]:
    safe_post_id = str(post_id or "").strip()
    if not safe_post_id:
        raise ValueError("post_id is required")

    safe_sort = str(sort or "top").lower()
    safe_limit = max(1, min(int(limit), 500))
    auth_mode = _get_auth_mode()

    comments: List[Dict[str, Any]] = []
    post_title = None
    post_permalink = None
    if auth_mode == "oauth":
        reddit = _get_reddit_client()
        submission = reddit.submission(id=safe_post_id)
        submission.comment_sort = safe_sort
        submission.comments.replace_more(limit=0)
        post_title = getattr(submission, "title", None)
        post_permalink = f"https://www.reddit.com{getattr(submission, 'permalink', '')}"
        for c in submission.comments.list()[:safe_limit]:
            comments.append(_comment_to_dict(c))
    else:
        url = f"https://www.reddit.com/comments/{safe_post_id}.json"
        params = {"sort": safe_sort, "limit": safe_limit}
        resp = requests.get(url, params=params, headers=_http_headers(), timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list) or len(payload) < 2:
            raise RuntimeError("Unexpected Reddit comments payload format.")

        post_children = payload[0].get("data", {}).get("children", []) or []
        if post_children:
            post_data = post_children[0].get("data", {}) or {}
            post_title = post_data.get("title")
            post_permalink = f"https://www.reddit.com{post_data.get('permalink', '')}"

        comment_children = payload[1].get("data", {}).get("children", []) or []
        comments = _flatten_comment_children(comment_children)[:safe_limit]

    return {
        "comments": comments,
        "meta": {
            "post_id": safe_post_id,
            "sort": safe_sort,
            "limit": safe_limit,
            "auth_mode": auth_mode,
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "post_title": post_title,
            "post_permalink": post_permalink,
        },
    }
