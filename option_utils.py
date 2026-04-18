"""Shared helpers for option-chain normalization and filtering."""
from __future__ import annotations

from typing import Any


def to_float(value: Any, default: float = 0.0) -> float:
    """Convert API values to float without leaking provider-specific blanks."""
    try:
        if value in ("", None):
            return float(default)
        result = float(value)
        return float(default) if result != result else result
    except (TypeError, ValueError):
        return float(default)


def to_int(value: Any, default: int = 0) -> int:
    """Convert API values to int, accepting numeric strings and floats."""
    try:
        if value in ("", None):
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def select_nearby_strikes(options: list[dict], current_price: float, strikes: int) -> list[dict]:
    """
    Select up to N strikes below and N strikes at/above current_price, sorted ascending.

    Providers return strikes as a mix of strings, floats, ints, and blanks. Keeping this
    logic in one place prevents small differences between CLI and MCP option output.
    """
    limit = max(0, int(strikes or 0))
    price = to_float(current_price, 0.0)

    valid_options = [opt for opt in options if to_float(opt.get("strike"), 0.0) > 0]
    below = sorted(
        [opt for opt in valid_options if to_float(opt.get("strike"), 0.0) < price],
        key=lambda opt: to_float(opt.get("strike"), 0.0),
        reverse=True,
    )[:limit]
    above = sorted(
        [opt for opt in valid_options if to_float(opt.get("strike"), 0.0) >= price],
        key=lambda opt: to_float(opt.get("strike"), 0.0),
    )[:limit]
    return sorted(below + above, key=lambda opt: to_float(opt.get("strike"), 0.0))
