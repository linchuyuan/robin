"""Market session calendar for US equities (NYSE/NASDAQ)."""

from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional

import pandas as pd
import pandas_market_calendars as mcal
import pytz

# US Eastern timezone
ET = pytz.timezone("America/New_York")

# Extended session times (US equities)
PREMARKET_OPEN_ET = (4, 0)     # 4:00 AM ET
REGULAR_OPEN_ET = (9, 30)      # 9:30 AM ET
REGULAR_CLOSE_ET = (16, 0)     # 4:00 PM ET
AFTERHOURS_CLOSE_ET = (20, 0)  # 8:00 PM ET


def _get_calendar():
    """Get the NYSE calendar (covers NASDAQ holidays too)."""
    return mcal.get_calendar("NYSE")


def get_market_status(dt: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Determine the current market session and schedule for today.

    Args:
        dt: Optional datetime to check. Defaults to now.

    Returns:
        Dictionary with session info, schedule, holidays, etc.
    """
    cal = _get_calendar()

    if dt is None:
        dt = datetime.now(ET)
    elif dt.tzinfo is None:
        dt = ET.localize(dt)
    else:
        dt = dt.astimezone(ET)

    today = dt.date()
    today_str = today.isoformat()

    result: Dict[str, Any] = {
        "timestamp": dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "date": today_str,
        "session": "closed",
        "is_trading_day": False,
        "is_early_close": False,
        "holiday": None,
        "schedule": {},
        "next_open": None,
        "next_close": None,
    }

    # Check if today is a trading day
    schedule_range = cal.schedule(
        start_date=(today - timedelta(days=1)).isoformat(),
        end_date=(today + timedelta(days=10)).isoformat(),
        start="pre",
        end="post",
    )

    if schedule_range.empty:
        result["holiday"] = "No trading days found in range"
        return result

    # Check if today is in the schedule
    today_ts = pd.Timestamp(today_str)
    if today_ts in schedule_range.index:
        result["is_trading_day"] = True
        row = schedule_range.loc[today_ts]

        pre_open = row["pre"].to_pydatetime()
        market_open = row["market_open"].to_pydatetime()
        market_close = row["market_close"].to_pydatetime()
        post_close = row["post"].to_pydatetime()

        # Check for early close (regular close before 4:00 PM ET)
        mc_et = market_close.astimezone(ET)
        if mc_et.hour < 16:
            result["is_early_close"] = True

        result["schedule"] = {
            "premarket_open": pre_open.astimezone(ET).strftime("%H:%M %Z"),
            "regular_open": market_open.astimezone(ET).strftime("%H:%M %Z"),
            "regular_close": mc_et.strftime("%H:%M %Z"),
            "afterhours_close": post_close.astimezone(ET).strftime("%H:%M %Z"),
        }

        # Determine current session
        dt_utc = dt.astimezone(pytz.utc)
        if dt_utc < pre_open:
            result["session"] = "closed"
            result["next_open"] = pre_open.astimezone(ET).strftime("%H:%M %Z")
        elif dt_utc < market_open:
            result["session"] = "pre-market"
            result["next_open"] = market_open.astimezone(ET).strftime("%H:%M %Z")
        elif dt_utc < market_close:
            result["session"] = "regular"
            result["next_close"] = mc_et.strftime("%H:%M %Z")
        elif dt_utc < post_close:
            result["session"] = "after-hours"
            result["next_close"] = post_close.astimezone(ET).strftime("%H:%M %Z")
        else:
            result["session"] = "closed"
    else:
        # Not a trading day -- figure out why
        # Check holidays
        holidays = cal.holidays()
        if holidays is not None:
            hol_index = holidays.holidays
            if today in hol_index:
                result["holiday"] = "Market Holiday"
            elif today.weekday() >= 5:
                result["holiday"] = "Weekend"
            else:
                result["holiday"] = "Market Holiday"

    # Find next trading day open (for "next_open" when closed)
    if result["session"] == "closed":
        future_days = schedule_range[schedule_range.index > today_ts]
        if future_days.empty:
            # Extend the range
            extended = cal.schedule(
                start_date=(today + timedelta(days=1)).isoformat(),
                end_date=(today + timedelta(days=30)).isoformat(),
                start="pre",
                end="post",
            )
            if not extended.empty:
                next_row = extended.iloc[0]
                next_date = extended.index[0].strftime("%Y-%m-%d")
                next_pre = next_row["pre"].to_pydatetime().astimezone(ET)
                result["next_open"] = f"{next_date} {next_pre.strftime('%H:%M %Z')}"
        else:
            next_row = future_days.iloc[0]
            next_date = future_days.index[0].strftime("%Y-%m-%d")
            next_pre = next_row["pre"].to_pydatetime().astimezone(ET)
            result["next_open"] = f"{next_date} {next_pre.strftime('%H:%M %Z')}"

    return result


def get_upcoming_holidays(limit: int = 5) -> List[Dict[str, str]]:
    """
    Get upcoming market holidays.

    Args:
        limit: Number of upcoming holidays to return.

    Returns:
        List of dicts with date and name.
    """
    cal = _get_calendar()
    today = date.today()

    # Get holidays for a broad range
    holidays = cal.holidays()
    if holidays is None:
        return []

    hol_dates = holidays.holidays
    upcoming = []
    for hol_date in sorted(hol_dates):
        # hol_date is a numpy datetime64 or date
        hol_d = pd.Timestamp(hol_date).date()
        if hol_d >= today:
            upcoming.append({
                "date": hol_d.isoformat(),
                "day": hol_d.strftime("%A"),
            })
            if len(upcoming) >= limit:
                break

    return upcoming


def get_early_closes(year: Optional[int] = None, limit: int = 10) -> List[Dict[str, str]]:
    """
    Get early close dates for a given year.

    Args:
        year: Year to check. Defaults to current year.
        limit: Max results.

    Returns:
        List of dicts with date and close time.
    """
    cal = _get_calendar()
    if year is None:
        year = date.today().year

    early = cal.early_closes(schedule=cal.schedule(
        start_date=f"{year}-01-01",
        end_date=f"{year}-12-31",
    ))

    result = []
    for idx, row in early.iterrows():
        close_et = row["market_close"].to_pydatetime().astimezone(ET)
        result.append({
            "date": idx.strftime("%Y-%m-%d"),
            "day": idx.strftime("%A"),
            "close_time": close_et.strftime("%H:%M %Z"),
        })
        if len(result) >= limit:
            break

    return result


if __name__ == "__main__":
    status = get_market_status()
    print(f"Time:       {status['timestamp']}")
    print(f"Session:    {status['session']}")
    print(f"Trading:    {status['is_trading_day']}")
    print(f"Early:      {status['is_early_close']}")
    print(f"Holiday:    {status['holiday']}")
    print(f"Schedule:   {status['schedule']}")
    print(f"Next Open:  {status['next_open']}")
    print(f"Next Close: {status['next_close']}")
    print()
    print("Upcoming holidays:")
    for h in get_upcoming_holidays():
        print(f"  {h['date']} ({h['day']})")
    print()
    print("Early closes this year:")
    for e in get_early_closes():
        print(f"  {e['date']} ({e['day']}) closes at {e['close_time']}")
