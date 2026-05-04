#!/usr/bin/env python3
"""Authentication helpers for Robinhood CLI."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import click
import robin_stocks.robinhood as rh
from robin_stocks.robinhood import authentication as rh_auth
from robin_stocks.robinhood import helper
from dotenv import load_dotenv

SESSION_CACHE = Path.home() / ".robinhood-cli" / "session.json"
ROBINHOOD_CLIENT_ID = "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS"
DEFAULT_TOKEN_EXPIRES_IN = 86400
DEFAULT_REFRESH_MARGIN_SECONDS = 3600


class AuthenticationError(click.ClickException):
    """Raised when a usable Robinhood session cannot be created."""


def load_environment() -> None:
    load_dotenv()


def prompt_credentials() -> tuple[str, str]:
    username = click.prompt("Robinhood username")
    password = click.prompt("Robinhood password", hide_input=True)
    return username, password


def get_credentials(mfa_code: Optional[str] = None) -> tuple[str, str, Optional[str]]:
    load_environment()
    username = os.getenv("ROBINHOOD_USERNAME")
    password = os.getenv("ROBINHOOD_PASSWORD")
    mfa = mfa_code or os.getenv("ROBINHOOD_MFA")
    if not username or not password:
        if os.getenv("MCP_SERVER_MODE"):
            raise AuthenticationError(
                "Authentication required. Set ROBINHOOD_USERNAME/ROBINHOOD_PASSWORD "
                "or run 'python cli.py login' before starting the MCP server."
            )
        username, password = prompt_credentials()
    return username, password, mfa


def _remove_invalid_cache() -> None:
    try:
        SESSION_CACHE.unlink()
    except FileNotFoundError:
        pass


def _extract_login_error(session: object) -> str:
    if isinstance(session, dict):
        for key in ("error", "detail", "message", "non_field_errors"):
            value = session.get(key)
            if value:
                return str(value)
    if session is None:
        return "Robinhood returned no session data."
    return f"Unexpected session response type: {type(session).__name__}."


def _refresh_margin_seconds() -> int:
    try:
        raw = os.getenv("ROBINHOOD_REFRESH_MARGIN_SECONDS")
        if raw in ("", None):
            return DEFAULT_REFRESH_MARGIN_SECONDS
        return max(60, int(float(raw)))
    except (TypeError, ValueError):
        return DEFAULT_REFRESH_MARGIN_SECONDS


def _now() -> float:
    return time.time()


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_session(session: dict, existing: dict | None = None) -> dict:
    data = dict(session)
    existing = existing or {}
    now = _now()
    expires_in = int(_to_float(data.get("expires_in"), _to_float(existing.get("expires_in"), DEFAULT_TOKEN_EXPIRES_IN)))
    created_at = _to_float(data.get("created_at"), _to_float(existing.get("created_at"), now))

    data["token_type"] = data.get("token_type") or existing.get("token_type") or "Bearer"
    data["expires_in"] = expires_in
    data["created_at"] = created_at
    data["expires_at"] = _to_float(data.get("expires_at"), created_at + expires_in)
    if not data.get("refresh_token") and existing.get("refresh_token"):
        data["refresh_token"] = existing["refresh_token"]
    if not data.get("scope") and existing.get("scope"):
        data["scope"] = existing["scope"]
    if existing.get("device_token") and not data.get("device_token"):
        data["device_token"] = existing["device_token"]
    return data


def _cache_session(session: dict, existing: dict | None = None) -> dict:
    data = _normalize_session(session, existing=existing)
    SESSION_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_CACHE.write_text(json.dumps(data))
    return data


def _session_expires_soon(data: dict) -> bool:
    expires_at = _to_float(data.get("expires_at"), 0.0)
    if expires_at <= 0:
        created_at = _to_float(data.get("created_at"), 0.0)
        expires_in = _to_float(data.get("expires_in"), 0.0)
        expires_at = created_at + expires_in if created_at > 0 and expires_in > 0 else 0.0
    if expires_at <= 0:
        return False
    return expires_at <= _now() + _refresh_margin_seconds()


def _refresh_session(data: dict) -> dict:
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        raise AuthenticationError(
            "Cached Robinhood session is expiring and has no refresh token. "
            "Run 'python cli.py login --mfa <code>' manually."
        )

    payload = {
        "client_id": ROBINHOOD_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": data.get("scope", "internal"),
    }
    if data.get("device_token"):
        payload["device_token"] = data["device_token"]

    refreshed = rh_auth.request_post(rh_auth.login_url(), payload)
    if not isinstance(refreshed, dict) or not refreshed.get("access_token"):
        raise AuthenticationError(
            "Robinhood session refresh failed; manual login is required. "
            f"{_extract_login_error(refreshed)}"
        )

    refreshed["created_at"] = _now()
    return _cache_session(refreshed, existing=data)


def _activate_session(data: dict) -> dict[str, str]:
    token = data.get("access_token")
    if not token:
        raise AuthenticationError("Cached Robinhood session is missing an access token.")

    token_type = data.get("token_type", "Bearer")
    rh.update_session("Authorization", f"{token_type} {token}")
    rh.globals.LOGGED_IN = True
    helper.LOGGED_IN = True
    return data


def get_session(mfa_code: Optional[str] = None) -> dict[str, str]:
    """Return a cached session or log in to Robinhood."""
    if SESSION_CACHE.exists():
        try:
            data = json.loads(SESSION_CACHE.read_text())
            if not isinstance(data, dict):
                _remove_invalid_cache()
            else:
                try:
                    data = _normalize_session(data)
                    if _session_expires_soon(data):
                        data = _refresh_session(data)
                    else:
                        # Persist metadata for older cache files without changing the token.
                        if "expires_at" not in data or "created_at" not in data:
                            _cache_session(data)
                    return _activate_session(data)
                except AuthenticationError:
                    if os.getenv("MCP_SERVER_MODE"):
                        raise
                    _remove_invalid_cache()
        except json.JSONDecodeError:
            _remove_invalid_cache()
    username, password, mfa = get_credentials(mfa_code)
    session = rh.login(username, password, mfa_code=mfa)
    if not isinstance(session, dict) or not session.get("access_token"):
        raise AuthenticationError(
            "Robinhood login failed; no access token was returned. "
            f"{_extract_login_error(session)}"
        )
    cached = _cache_session({**session, "created_at": _now()})
    return _activate_session(cached)


def logout() -> None:
    """Clear the cached session."""
    if SESSION_CACHE.exists():
        SESSION_CACHE.unlink()
    rh.logout()
