"""
mf_data.py
Client for the free mfapi.in API (no auth). Provides fund search and NAV history.
Light in-memory cache to avoid hammering the API during a conversation.
"""
import time
import requests

BASE = "https://api.mfapi.in"
_TIMEOUT = 15
_cache = {}
_CACHE_TTL = 3600  # 1 hour


def _get(url: str):
    now = time.time()
    if url in _cache and now - _cache[url][0] < _CACHE_TTL:
        return _cache[url][1]
    resp = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "sip-advisor-agent/1.0"})
    resp.raise_for_status()
    data = resp.json()
    _cache[url] = (now, data)
    return data


def search_funds(query: str, limit: int = 8):
    """
    Search schemes by name. Returns a trimmed list of {schemeCode, schemeName}.
    Prefers Direct + Growth plans (better for long-term SIP investors) by sorting them up.
    """
    try:
        results = _get(f"{BASE}/mf/search?q={requests.utils.quote(query)}")
    except Exception as e:
        return {"error": f"Fund search failed: {e}"}
    if not isinstance(results, list):
        return {"error": "Unexpected search response."}

    def score(name: str) -> int:
        n = name.lower()
        s = 0
        if "direct" in n: s += 2
        if "growth" in n: s += 1
        if "idcw" in n or "dividend" in n: s -= 1
        return -s  # lower sorts first
    results.sort(key=lambda r: score(r.get("schemeName", "")))
    trimmed = [{"schemeCode": r["schemeCode"], "schemeName": r["schemeName"]} for r in results[:limit]]
    return {"count": len(trimmed), "results": trimmed}


def get_fund(scheme_code: int):
    """
    Full scheme record: meta (fund house, category, ISIN) + full NAV history.
    Returns {meta, data} where data is newest-first [{date, nav}].
    """
    try:
        data = _get(f"{BASE}/mf/{int(scheme_code)}")
    except Exception as e:
        return {"error": f"Could not fetch scheme {scheme_code}: {e}"}
    if not isinstance(data, dict) or "data" not in data:
        return {"error": "Unexpected scheme response."}
    return data


def get_latest_nav(scheme_code: int):
    try:
        data = _get(f"{BASE}/mf/{int(scheme_code)}/latest")
    except Exception as e:
        return {"error": f"Could not fetch latest NAV for {scheme_code}: {e}"}
    return data
