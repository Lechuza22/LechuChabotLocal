from __future__ import annotations

import httpx

from core.tools import Tool, register

SEARCH_URL = "https://{lang}.wikipedia.org/w/api.php"
SUMMARY_URL = "https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}"


def search_wikipedia(query: str, lang: str = "es") -> dict:
    with httpx.Client(timeout=10.0, headers={"User-Agent": "Lechu/1.0"}) as client:
        search_resp = client.get(SEARCH_URL.format(lang=lang), params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 1,
            "format": "json",
        })
        search_resp.raise_for_status()
        results = search_resp.json().get("query", {}).get("search", [])
        if not results:
            return {"error": f"No se encontró nada en Wikipedia para '{query}'."}
        title = results[0]["title"]

        summary_resp = client.get(SUMMARY_URL.format(lang=lang, title=title))
        summary_resp.raise_for_status()
        summary = summary_resp.json()

    return {
        "title": summary.get("title", title),
        "description": summary.get("description"),
        "extract": summary.get("extract"),
        "url": summary.get("content_urls", {}).get("desktop", {}).get("page"),
    }


register(Tool(
    name="search_wikipedia",
    description="Search Wikipedia for a topic and return a short summary. No API key required.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Topic or search term"},
            "lang": {"type": "string", "description": "Wikipedia language code, defaults to 'es'"},
        },
        "required": ["query"],
    },
    func=search_wikipedia,
))
