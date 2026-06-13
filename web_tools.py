"""
web_tools.py
Current market context via Tavily (primary) and Firecrawl (optional deep fetch).
Both keys are optional — the agent still works on fund data + math without them.
"""
import os
import requests

_TIMEOUT = 20


def web_search(query: str, max_results: int = 5):
    """Search the web for current MF / market context using Tavily."""
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        return {"error": "TAVILY_API_KEY not set; web context unavailable."}
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": True,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        d = resp.json()
        return {
            "answer": d.get("answer"),
            "results": [
                {"title": r.get("title"), "url": r.get("url"),
                 "content": (r.get("content") or "")[:600]}
                for r in d.get("results", [])
            ],
        }
    except Exception as e:
        return {"error": f"Web search failed: {e}"}


def fetch_page(url: str):
    """Deep-extract a single page's main content via Firecrawl (optional)."""
    key = os.getenv("FIRECRAWL_API_KEY")
    if not key:
        return {"error": "FIRECRAWL_API_KEY not set."}
    try:
        resp = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={"Authorization": f"Bearer {key}"},
            json={"url": url, "formats": ["markdown"]},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        d = resp.json()
        md = (d.get("data", {}) or {}).get("markdown", "")
        return {"url": url, "content": md[:4000]}
    except Exception as e:
        return {"error": f"Page fetch failed: {e}"}
