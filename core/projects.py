from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

LECHU_DIR_NAME = ".lechu"
MARKER_FILE = "project.json"
FACTS_FILE = "facts.json"


def lechu_dir(folder: Path) -> Path:
    return folder / LECHU_DIR_NAME


def read_marker(folder: Path) -> dict | None:
    marker = lechu_dir(folder) / MARKER_FILE
    if not marker.exists():
        return None
    try:
        return json.loads(marker.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def write_marker(folder: Path, name: str, project_id: int) -> None:
    lechu_dir(folder).mkdir(parents=True, exist_ok=True)
    marker = lechu_dir(folder) / MARKER_FILE
    marker.write_text(json.dumps(
        {"name": name, "lechu_project_id": project_id, "created_at": datetime.now().isoformat()},
        indent=2,
    ))


# --- project-scoped facts (.lechu/facts.json) --------------------------------

def _facts_path(folder: Path) -> Path:
    return lechu_dir(folder) / FACTS_FILE


def _load_facts(folder: Path) -> list[dict]:
    path = _facts_path(folder)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text()).get("facts", [])
    except (json.JSONDecodeError, OSError):
        return []


def _save_facts(folder: Path, facts: list[dict]) -> None:
    lechu_dir(folder).mkdir(parents=True, exist_ok=True)
    _facts_path(folder).write_text(json.dumps({"facts": facts}, indent=2, ensure_ascii=False))


def remember_fact_in_folder(folder: Path, category: str, key: str, value: str, source: str = "user") -> None:
    facts = _load_facts(folder)
    now = datetime.now().isoformat()
    for fact in facts:
        if fact["category"] == category and fact["key"] == key:
            fact["value"] = value
            fact["source"] = source
            fact["updated_at"] = now
            break
    else:
        facts.append({
            "category": category, "key": key, "value": value,
            "source": source, "created_at": now, "updated_at": now,
        })
    _save_facts(folder, facts)


def recall_facts_in_folder(folder: Path, category: str | None = None) -> list[dict]:
    facts = _load_facts(folder)
    if category:
        facts = [f for f in facts if f["category"] == category]
    return sorted(facts, key=lambda f: f["updated_at"], reverse=True)


def delete_fact_in_folder(folder: Path, category: str, key: str) -> None:
    facts = _load_facts(folder)
    facts = [f for f in facts if not (f["category"] == category and f["key"] == key)]
    _save_facts(folder, facts)
