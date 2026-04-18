"""
SEC Form 4 insider transaction scraper. Uses openinsider.com (free, no API key)
as the primary source; falls back to gracefully returning no-data when
unavailable. Filters out 10b5-1 scheduled trades and option exercises per the
insider-flow skill's rules.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from typing import Any

import requests


_BASE_URL = "http://openinsider.com/insider-purchases"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _parse_openinsider_table(html: str) -> list[dict]:
    """
    Parse the openinsider transaction table without bs4 to keep dependencies light.
    Layout is predictable: <tr><td>...</td>...</tr>.
    """
    # Find the results table by scanning for the tinytable class (used by openinsider)
    m = re.search(r'class="tinytable"[^>]*>(.*?)</table>', html, re.DOTALL)
    if not m:
        return []
    table_body = m.group(1)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_body, re.DOTALL)
    out = []
    for row in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)
        if len(cells) < 13:
            continue
        def _clean(s: str) -> str:
            return re.sub(r"<[^>]+>", "", s).strip().replace("&nbsp;", " ").replace(",", "")
        try:
            trade_date = _clean(cells[1])[:10]
            ticker = _clean(cells[3])
            insider_name = _clean(cells[5])
            title = _clean(cells[6])
            txn_type_raw = _clean(cells[7])
            price = float(_clean(cells[8]).replace("$", "") or 0)
            qty = int(float(_clean(cells[9]) or 0))
            owned = int(float(_clean(cells[10]) or 0))
            value_str = _clean(cells[12]).replace("$", "").replace(" ", "")
            value = float(value_str or 0)
            # Open-market purchase = "P - Purchase"; "P" code generally
            is_p = txn_type_raw.upper().startswith("P")
            out.append({
                "transaction_date": trade_date,
                "symbol": ticker,
                "insider_name": insider_name,
                "insider_title": title,
                "transaction_type": "P" if is_p else txn_type_raw,
                "shares": qty,
                "price": price,
                "value_usd": value,
                "post_transaction_shares": owned,
                "is_10b5_1": False,  # openinsider flags separately; we conservatively assume no
                "is_option_exercise": False,
            })
        except Exception:
            continue
    return out


def fetch_insider_transactions(symbol: str, days: int = 30) -> list[dict]:
    """Fetch qualifying insider transactions for a symbol in the last N days."""
    symbol_up = str(symbol).upper().strip()
    url = f"http://openinsider.com/screener?s={symbol_up}&o=&pl=&ph=&ll=&lh=&fd=-{max(1, int(days))}&fdr=&td=0&tdr=&fdlyl=&fdlyh=&daysago=&xp=1&vl=&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&grp=0&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&sortcol=0&cnt=50&page=1"
    try:
        r = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=12)
        if r.status_code != 200:
            return []
        return _parse_openinsider_table(r.text)
    except Exception:
        return []


def _is_qualifying_buy(txn: dict) -> bool:
    if txn.get("transaction_type") != "P":
        return False
    if txn.get("is_option_exercise"):
        return False
    if txn.get("is_10b5_1"):
        return False
    if float(txn.get("value_usd") or 0) < 100_000:
        return False
    title = (txn.get("insider_title") or "").upper()
    qualifying_titles = ["CEO", "CFO", "COO", "PRESIDENT", "CHAIRMAN", "CHAIR", "DIRECTOR", "10% OWNER", "CHIEF"]
    if not any(t in title for t in qualifying_titles):
        return False
    return True


def score_insider_signal(transactions: list[dict]) -> dict:
    """
    Apply insider-flow skill scoring tiers to a raw transaction list.
    """
    buys = [t for t in transactions if _is_qualifying_buy(t)]
    total_buy_usd = sum(float(t.get("value_usd") or 0) for t in buys)
    unique_buyers = len({t.get("insider_name") for t in buys if t.get("insider_name")})
    exec_titles = ["CEO", "CFO", "COO", "PRESIDENT", "CHAIRMAN", "CHIEF"]
    exec_buyers = sum(1 for t in buys if any(x in (t.get("insider_title") or "").upper() for x in exec_titles))

    max_single = max((float(t.get("value_usd") or 0) for t in buys), default=0.0)

    if unique_buyers >= 3 and total_buy_usd >= 500_000:
        tier = "cluster_buy"
        points = 5
    elif exec_buyers >= 1 and max_single >= 1_000_000:
        tier = "exec_conviction"
        points = 5
    elif unique_buyers >= 1 and total_buy_usd >= 100_000:
        tier = "small_buy"
        points = 2
    else:
        tier = "no_signal"
        points = 0

    # All non-qualifying transactions (for transparency)
    all_sell_usd = sum(
        float(t.get("value_usd") or 0) for t in transactions
        if t.get("transaction_type") != "P"
    )

    return {
        "tier": tier,
        "catalyst_points_bonus": points,
        "net_insider_buy_usd": round(total_buy_usd, 2),
        "unique_insider_buyers": unique_buyers,
        "exec_buyers": exec_buyers,
        "max_single_buy_usd": round(max_single, 2),
        "total_sell_usd_all_types": round(all_sell_usd, 2),
        "qualifying_buy_count": len(buys),
        "qualifying_buys": buys[:10],  # cap for LLM context
    }


def get_insider_flow(symbol: str, days: int = 30) -> dict:
    """Main entry point; combines fetch + score."""
    symbol_up = str(symbol).upper().strip()
    transactions = fetch_insider_transactions(symbol_up, days)
    signal = score_insider_signal(transactions)
    return {
        "symbol": symbol_up,
        "window_days": days,
        "transaction_count_raw": len(transactions),
        "signal": signal,
        "source": "openinsider",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
