from __future__ import annotations

from core import memory
from core.tools import Tool, register


def remember_fact(category: str, key: str, value: str) -> dict:
    memory.remember_fact(category=category, key=key, value=value, source="agent_inferred")
    return {"remembered": {"category": category, "key": key, "value": value}}


def recall_facts(category: str | None = None) -> dict:
    rows = memory.recall_facts(category=category)
    return {"facts": [{"category": r["category"], "key": r["key"], "value": r["value"]} for r in rows]}


register(Tool(
    name="remember_fact",
    description="Store a fact, preference, or piece of context about the user for future conversations.",
    parameters={
        "type": "object",
        "properties": {
            "category": {"type": "string", "description": "e.g. 'preference', 'project_context', 'personal_fact'"},
            "key": {"type": "string", "description": "Short identifier for this fact, e.g. 'favorite_editor'"},
            "value": {"type": "string", "description": "The fact's value"},
        },
        "required": ["category", "key", "value"],
    },
    func=remember_fact,
))

register(Tool(
    name="recall_facts",
    description="Retrieve previously remembered facts about the user, optionally filtered by category.",
    parameters={
        "type": "object",
        "properties": {
            "category": {"type": "string", "description": "Optional category filter"},
        },
        "required": [],
    },
    func=recall_facts,
))
