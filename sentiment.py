"""Market sentiment helpers (Fear & Greed, VIX, yield curve, breadth)."""
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


def get_yield_curve() -> Dict[str, Any]:
    """
    Fetch US Treasury yield curve data (2Y/10Y spread) from Yahoo Finance.
    Inverted yield curve (negative spread) is a recession signal.
    """
    try:
        tnx = yf.Ticker("^TNX")  # 10-year
        try:
            two_year = yf.Ticker("2YY=F")
            two_year_info = two_year.info or {}
            yield_2y = two_year_info.get("regularMarketPrice") or two_year_info.get("previousClose")
            short_end_instrument = "2YY=F"
        except Exception:
            yield_2y = None
            short_end_instrument = None

        if yield_2y is None:
            twoy = yf.Ticker("^IRX")  # 13-week T-bill as fallback
            twoy_info = twoy.info or {}
            yield_2y = twoy_info.get("regularMarketPrice") or twoy_info.get("previousClose")
            short_end_instrument = "^IRX"

        tnx_info = tnx.info or {}
        yield_10y = tnx_info.get("regularMarketPrice") or tnx_info.get("previousClose")

        if yield_10y is None or yield_2y is None:
            return {"error": "Could not fetch yield data"}

        yield_10y = float(yield_10y)
        yield_2y = float(yield_2y)
        spread = round(yield_10y - yield_2y, 4)

        signal = "normal"
        if spread < 0:
            signal = "inverted"
        elif spread < 0.25:
            signal = "flat"

        return {
            "yield_10y": yield_10y,
            "yield_2y": yield_2y if short_end_instrument == "2YY=F" else None,
            "yield_short_proxy": yield_2y,
            "short_end_instrument": short_end_instrument,
            "spread_10y_2y": spread,
            "spread_10y_short_proxy": spread,
            "signal": signal,
            "warning": "short end uses ^IRX 13-week bill proxy, not true 2Y yield" if short_end_instrument == "^IRX" else None,
        }
    except Exception as e:
        return {"error": str(e)}


def get_market_breadth() -> Dict[str, Any]:
    """
    Fetch market breadth using sector ETF advance/decline as proxy.
    """
    try:
        sectors = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLC", "XLY", "XLP", "XLU", "XLRE", "XLB"]
        data = yf.download(sectors, period="5d", progress=False, auto_adjust=False)
        if data is None or data.empty:
            return {"error": "No breadth data available"}

        close = data["Close"] if "Close" in data else data
        advancing = 0
        declining = 0
        for sym in sectors:
            try:
                series = close[sym] if sym in close.columns else None
                if series is not None and len(series.dropna()) >= 2:
                    ret = float(series.dropna().iloc[-1] / series.dropna().iloc[0] - 1)
                    if ret > 0:
                        advancing += 1
                    else:
                        declining += 1
            except Exception:
                continue

        ad_ratio = round(advancing / max(declining, 1), 2)
        breadth_signal = "healthy" if ad_ratio > 1.5 else ("weak" if ad_ratio < 0.7 else "mixed")

        return {
            "advancing_sectors": advancing,
            "declining_sectors": declining,
            "ad_ratio": ad_ratio,
            "breadth_signal": breadth_signal,
            "period": "5d",
        }
    except Exception as e:
        return {"error": str(e)}
