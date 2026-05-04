import requests
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

LAST_MACRO_NEWS_META: Dict[str, Any] = {}


def get_macro_news_meta() -> Dict[str, Any]:
    return dict(LAST_MACRO_NEWS_META)


def get_macro_news(limit: int = 5, only_today: bool = False) -> List[Dict[str, str]]:
    """
    Fetch and aggregate latest macroeconomic news from Investing.com, Bloomberg, and CNBC.
    
    Args:
        limit: Number of total news items to return.
        only_today: If True, only return news published today (local time).
        
    Returns:
        List of dictionaries containing title, link, published, summary, and source.
    """
    
    sources = {
        "Investing.com": "https://www.investing.com/rss/news_14.rss",
        "Bloomberg": "https://feeds.bloomberg.com/economics/news.rss",
        "CNBC": "https://www.cnbc.com/id/20910258/device/rss/rss.html"
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
    }
    
    all_news = []
    sources_failed = []
    sources_ok = []
    # Use local date for "today" filtering
    today_local = datetime.now().date()
    
    for source_name, url in sources.items():
        try:
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code != 200:
                sources_failed.append({"source": source_name, "error": f"http_{response.status_code}"})
                continue
                
            # Parse XML
            root = ET.fromstring(response.content)
            items = root.findall("./channel/item")
            sources_ok.append(source_name)
            
            for item in items:
                pub_date_str = item.find("pubDate").text if item.find("pubDate") is not None else ""
                
                dt_obj = None
                if pub_date_str:
                    try:
                        # Investing.com format: YYYY-MM-DD HH:MM:SS (Usually GMT/UTC but naive)
                        # CNBC/Bloomberg format: RFC 2822 (Aware)
                        if "," in pub_date_str:
                             dt_obj = parsedate_to_datetime(pub_date_str)
                        else:
                             dt_obj = datetime.strptime(pub_date_str, "%Y-%m-%d %H:%M:%S")
                             # Assume Investing.com is UTC
                             dt_obj = dt_obj.replace(tzinfo=timezone.utc)
                    except Exception:
                        pass
                
                # Filter for today if requested
                # Convert to local system time for "today" check
                if only_today:
                     if not dt_obj:
                         continue
                     # Convert to local time
                     dt_local = dt_obj.astimezone(None)
                     if dt_local.date() != today_local:
                         continue

                title = item.find("title").text if item.find("title") is not None else "No Title"
                link = item.find("link").text if item.find("link") is not None else ""
                description = item.find("description").text if item.find("description") is not None else ""
                
                parsed_at_unknown = dt_obj is None
                sort_date = dt_obj if dt_obj else datetime.min.replace(tzinfo=timezone.utc)

                all_news.append({
                    "title": title,
                    "link": link,
                    "published": pub_date_str,
                    "summary": description,
                    "source": source_name,
                    "parsed_at_unknown": parsed_at_unknown,
                    "_sort_date": sort_date
                })
                
        except Exception as e:
            sources_failed.append({"source": source_name, "error": str(e)})
            continue
            
    # Sort by date descending (newest first)
    # All _sort_date should now be timezone-aware (UTC or otherwise)
    all_news.sort(key=lambda x: x["_sort_date"], reverse=True)
    
    # Remove internal sort key and limit
    result = []
    for n in all_news[:limit]:
        n_copy = n.copy()
        del n_copy["_sort_date"]
        result.append(n_copy)
        
    global LAST_MACRO_NEWS_META
    LAST_MACRO_NEWS_META = {
        "sources_ok": sources_ok,
        "sources_failed": sources_failed,
        "partial": bool(sources_failed),
        "fetched_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
         
    return result

if __name__ == "__main__":
    # Test the function
    news = get_macro_news()
    for n in news:
        print(f"- {n.get('title')} ({n.get('published')})")
