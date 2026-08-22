from __future__ import annotations

import httpx

from config import CONFIG
from core.secrets import get_secret
from core.tools import Tool, register

SEARCH_URL = "https://api.tavily.com/search"

API_KEY_SECRET = "tavily_api_key"

# Same model every agent in this project uses today - tools have no notion
# of "which agent/model called me", so this is hardcoded rather than
# threaded through from the caller.
_VARIANT_MODEL = "qwen3:8b"

_NOT_CONNECTED = {
    "error": (
        "Búsqueda web no configurada. Pedile al usuario que cargue su API key de Tavily "
        "en Configuración → Conexiones → Búsqueda web."
    )
}


def _generate_query_variants(topic: str, n: int) -> list[str]:
    """Up to `n` alternate phrasings of `topic`, via a plain (non-tool) chat
    call to the local model - best-effort: any failure just returns [], so
    search_web degrades to the literal query alone rather than breaking."""
    if n <= 0:
        return []
    prompt = (
        f"Give me {n} different ways to search for information about: {topic!r}\n"
        f"Different angles/keywords, not just rewordings. One per line, no numbering, "
        f"no explanations - just the {n} search queries."
    )
    try:
        # Generous timeout: a cold Ollama needs to load the model into memory
        # on its first call in a while, which alone can take longer than a
        # normal request - confirmed hitting this during testing.
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(f"{CONFIG.ollama_base_url}/api/chat", json={
                "model": _VARIANT_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            })
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
    except (httpx.HTTPError, KeyError):
        return []

    lines = [line.strip("-•* \t") for line in content.splitlines()]
    return [line for line in lines if line][:n]


def search_web(query: str, num_results: int = 5, num_variants: int = 3) -> dict:
    """Runs up to `num_variants` real searches (the literal query plus
    model-generated alternate phrasings) and returns the combined, deduped
    results, via Tavily (Google's Custom Search API is closed to new
    projects as of 2025) - see Configuración → Conexiones → Búsqueda web."""
    api_key = get_secret(API_KEY_SECRET)
    if not api_key:
        return _NOT_CONNECTED

    num_variants = max(1, min(num_variants, 5))
    queries = [query] + _generate_query_variants(query, num_variants - 1)

    seen_urls: set[str] = set()
    combined: list[dict] = []
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=15.0) as client:
        for q in queries:
            resp = client.post(SEARCH_URL, headers=headers, json={
                "query": q,
                "max_results": max(1, min(num_results, 10)),
            })
            if resp.status_code != 200:
                continue  # one bad variant shouldn't sink the whole search
            for item in resp.json().get("results", []):
                url = item.get("url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                combined.append({"title": item.get("title"), "url": url, "snippet": item.get("content")})

    if not combined:
        return {"error": f"No se encontraron resultados para '{query}'."}
    return {"results": combined, "queries_used": queries}


def test_connection() -> bool:
    """UI-only helper for the Configuración → Conexiones → Búsqueda web
    'Probar conexión' button - not a registered LLM tool. A single direct
    query (not search_web) so testing the key doesn't burn multiple quota
    units on query variants."""
    api_key = get_secret(API_KEY_SECRET)
    if not api_key:
        return False
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            SEARCH_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"query": "Argentina", "max_results": 1},
        )
    return resp.status_code == 200


register(Tool(
    name="search_web",
    description=(
        "Search the web. Automatically tries several phrasings of the query "
        "(different angles/keywords) and returns the combined, deduplicated results - don't "
        "call it multiple times yourself with manual variations. Requires an API key configured "
        "by the user in Configuración → Conexiones → Búsqueda web."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "num_results": {"type": "integer", "description": "Results per query variant, 1-10, defaults to 5"},
            "num_variants": {
                "type": "integer",
                "description": (
                    "How many different phrasings to try (including the literal query), 1-5, "
                    "defaults to 3. Each variant is a real search call against the monthly quota."
                ),
            },
        },
        "required": ["query"],
    },
    func=search_web,
))
