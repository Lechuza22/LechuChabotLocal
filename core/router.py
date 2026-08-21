from __future__ import annotations

import httpx

from config import CONFIG

# Same model every agent in this project uses today - same simplification
# already made in core/tools/websearch_tools.py::_generate_query_variants.
_ROUTER_MODEL = "qwen3:8b"

# No entry for "general" - it's the implicit result when nothing else
# scores, not something to match keywords against.
_KEYWORD_RULES: dict[str, list[str]] = {
    "coder": [
        "código", "codigo", "function", "función", "funcion", "bug", "script",
        "clase", "variable", "compilar", "refactor", "debug", "programa",
        "python", "javascript", "typescript", "html", "css", "sql", "archivo .py",
    ],
    "google": [
        "mail", "correo", "gmail", "calendario", "evento", "reunión", "reunion",
        "drive", "agenda", "invitá", "invita", "meeting",
    ],
    "search": [
        "buscá", "busca", "búsqueda", "busqueda", "wikipedia", "internet",
        "googlealo", "investigá", "investiga", "noticias",
    ],
}


def _classify_with_llm(text: str, agent_ids: list[str]) -> str | None:
    """Best-effort tie-breaker via a plain (non-tool) chat call to the local
    model - any failure returns None so the caller falls back to staying on
    the current agent instead of breaking."""
    options = ", ".join(agent_ids)
    prompt = (
        f"Classify this user message into exactly one category: {options}.\n"
        "- coder: writing, debugging, or explaining code\n"
        "- google: email, calendar, or Google Drive files\n"
        "- search: looking something up online or on Wikipedia\n"
        "- general: anything else\n\n"
        f'Message: "{text}"\n\n'
        "Reply with just the category word, nothing else."
    )
    try:
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(f"{CONFIG.ollama_base_url}/api/chat", json={
                "model": _ROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            })
            resp.raise_for_status()
            content = resp.json()["message"]["content"].strip().lower()
    except (httpx.HTTPError, KeyError):
        return None

    for agent_id in agent_ids:
        if agent_id in content:
            return agent_id
    return None


def route_agent(text: str, agent_ids: list[str], current_agent_id: str) -> str:
    """Which agent should answer this message. Only switches away from
    `current_agent_id` when there's a concrete reason to (a clear keyword
    winner, or the model breaking a tie) - a message with no signal of its
    own (e.g. "dale, probalo" mid-conversation) stays on whatever agent was
    already active instead of resetting to general."""
    lowered = text.lower()
    scores = {
        agent_id: sum(1 for kw in keywords if kw in lowered)
        for agent_id, keywords in _KEYWORD_RULES.items()
        if agent_id in agent_ids
    }
    top_score = max(scores.values(), default=0)
    if top_score == 0:
        return current_agent_id

    winners = [agent_id for agent_id, score in scores.items() if score == top_score]
    if len(winners) == 1:
        return winners[0]

    classified = _classify_with_llm(text, agent_ids)
    if classified and classified in agent_ids:
        return classified
    return current_agent_id
