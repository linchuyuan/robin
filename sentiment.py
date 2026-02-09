"""Market sentiment helpers (Fear & Greed, VIX)."""
import requests
import yfinance as yf
from typing import Dict, Any, Optional

def get_fear_and_greed() -> Dict[str, Any]:
    """
    Fetch CNN Fear & Greed Index.
    Returns dictionary with score, rating, and timestamp.
    """
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {
        'authority': 'production.dataviz.cnn.io',
        'accept': '*/*',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        'origin': 'https://edition.cnn.com',
        'referer': 'https://edition.cnn.com/',
        'sec-fetch-site': 'cross-site',
        'sec-fetch-mode': 'cors',
        'sec-fetch-dest': 'empty',
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            fg_data = data.get('fear_and_greed', {})
            return {
                "score": float(fg_data.get('score', 0)),
                "rating": fg_data.get('rating', 'unknown'),
                "previous_close": float(fg_data.get('previous_close', 0)),
                "timestamp": fg_data.get('timestamp')
            }
        else:
            return {"error": f"Failed to fetch Fear & Greed (Status {r.status_code})"}
    except Exception as e:
        return {"error": str(e)}

def get_vix() -> Dict[str, Any]:
    """
    Fetch VIX (Volatility Index) from Yahoo Finance.
    """
    try:
        ticker = yf.Ticker("^VIX")
        info = ticker.info
        # Yahoo finance keys vary; try reliable ones for indices
        price = info.get("regularMarketPrice") or info.get("currentPrice") or info.get("last_price")
        prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
        
        # Calculate change if possible
        change = 0.0
        pct_change = 0.0
        if price and prev:
            change = price - prev
            pct_change = (change / prev) * 100
            
        return {
            "price": price,
            "previous_close": prev,
            "change": change,
            "percent_change": pct_change,
            "day_high": info.get("dayHigh"),
            "day_low": info.get("dayLow"),
            "52_week_high": info.get("fiftyTwoWeekHigh"),
            "52_week_low": info.get("fiftyTwoWeekLow")
        }
    except Exception as e:
        return {"error": str(e)}
