"""Authentication helpers for Robinhood CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import click
import robin_stocks.robinhood as rh
from dotenv import load_dotenv

SESSION_CACHE = Path.home() / ".robinhood-cli" / "session.json"


def load_environment() -> None:
    load_dotenv()


def prompt_credentials() -> tuple[str, str]:
    username = click.prompt("Robinhood username")
    password = click.prompt("Robinhood password", hide_input=True)
    return username, password


def get_credentials() -> tuple[str, str, Optional[str]]:
    load_environment()
    username = os.getenv("ROBINHOOD_USERNAME")
    password = os.getenv("ROBINHOOD_PASSWORD")
    mfa = os.getenv("ROBINHOOD_MFA")
    if not username or not password:
        username, password = prompt_credentials()
    return username, password, mfa


def get_session() -> dict[str, str]:
    """Return a cached session or log in to Robinhood."""
    if SESSION_CACHE.exists():
        try:
            return json.loads(SESSION_CACHE.read_text())
        except json.JSONDecodeError:
            SESSION_CACHE.unlink()
    username, password, mfa = get_credentials()
    session = rh.login(username, password, mfa_code=mfa)
    SESSION_CACHE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_CACHE.write_text(json.dumps(session))
    return session


def logout() -> None:
    """Clear the cached session."""
    if SESSION_CACHE.exists():
        SESSION_CACHE.unlink()
    rh.logout()
