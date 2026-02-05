import requests
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
from datetime import datetime

def get_macro_news(limit: int = 5) -> List[Dict[str, str]]:
    """
    Fetch the latest macroeconomic news from CNBC's Economy RSS feed.
    
    Args:
        limit: Number of news items to return.
        
    Returns:
        List of dictionaries containing title, link, pubDate, and description.
    """
    url = "https://www.cnbc.com/id/20910258/device/rss/rss.html"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Parse XML
        root = ET.fromstring(response.content)
        
        # Find channel/item elements
        items = root.findall("./channel/item")
        
        news_list = []
        for item in items[:limit]:
            title = item.find("title").text if item.find("title") is not None else "No Title"
            link = item.find("link").text if item.find("link") is not None else ""
            pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
            description = item.find("description").text if item.find("description") is not None else ""
            
            # Clean up description (sometimes has HTML)
            # basic clean, removing simple tags if needed, but for CLI raw text is usually okay if not too messy.
            # CNBC descriptions are usually plain text summaries.
            
            news_list.append({
                "title": title,
                "link": link,
                "published": pub_date,
                "summary": description
            })
            
        return news_list
        
    except Exception as e:
        return [{"error": f"Failed to fetch news: {str(e)}"}]

if __name__ == "__main__":
    # Test the function
    news = get_macro_news()
    for n in news:
        print(f"- {n.get('title')} ({n.get('published')})")
