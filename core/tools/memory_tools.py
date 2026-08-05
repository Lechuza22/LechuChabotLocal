from __future__ import annotations

from pathlib import Path

from core import memory, projects
from core.tools import Tool, register

# Facts default to the global SQLite store, but a folder-backed project
# (opened via "Abrir carpeta...") scopes them to that folder's .lechu/facts.json
# instead - see set_memory_scope().
_active_project_folder: Path | None = None


def set_memory_scope(folder_path: str | None) -> None:
    global _active_project_folder
    _active_project_folder = Path(folder_path) if folder_path else None


def remember_fact(category: str, key: str, value: str) -> dict:
    if _active_project_folder:
        projects.remember_fact_in_folder(_active_project_folder, category, key, value, source="agent_inferred")
    else:
        memory.remember_fact(category=category, key=key, value=value, source="agent_inferred")
    return {"remembered": {"category": category, "key": key, "value": value}}


def recall_facts(category: str | None = None) -> dict:
    if _active_project_folder:
        rows = projects.recall_facts_in_folder(_active_project_folder, category)
        facts = [{"category": r["category"], "key": r["key"], "value": r["value"]} for r in rows]
    else:
        rows = memory.recall_facts(category=category)
        facts = [{"category": r["category"], "key": r["key"], "value": r["value"]} for r in rows]
    return {"facts": facts}


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
