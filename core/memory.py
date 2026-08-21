from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    folder_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    agent_id TEXT NOT NULL,
    model TEXT NOT NULL,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user','assistant','tool','system')),
    content TEXT,
    tool_calls TEXT,
    tool_call_id TEXT,
    tool_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user',
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(category, key)
);
CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)
        conv_cols = {row["name"] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()}
        if "project_id" not in conv_cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN project_id INTEGER REFERENCES projects(id)")
        project_cols = {row["name"] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "folder_path" not in project_cols:
            conn.execute("ALTER TABLE projects ADD COLUMN folder_path TEXT")


# --- projects ------------------------------------------------------------

def create_project(name: str, folder_path: str | None = None) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, folder_path) VALUES (?, ?)", (name, folder_path)
        )
        return cur.lastrowid


def list_projects() -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            "SELECT id, name, folder_path, created_at FROM projects ORDER BY name"
        ).fetchall()


def find_project_by_folder(folder_path: str) -> sqlite3.Row | None:
    with _connect() as conn:
        return conn.execute(
            "SELECT id, name, folder_path, created_at FROM projects WHERE folder_path = ?",
            (folder_path,),
        ).fetchone()


def get_project(project_id: int) -> sqlite3.Row | None:
    with _connect() as conn:
        return conn.execute(
            "SELECT id, name, folder_path, created_at FROM projects WHERE id = ?", (project_id,)
        ).fetchone()


# --- conversations -----------------------------------------------------

def create_conversation(agent_id: str, model: str, project_id: int | None = None, title: str | None = None) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (title, agent_id, model, project_id) VALUES (?, ?, ?, ?)",
            (title, agent_id, model, project_id),
        )
        return cur.lastrowid


def touch_conversation(conversation_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
            (conversation_id,),
        )


def set_conversation_title(conversation_id: int, title: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)
        )


def get_conversation(conversation_id: int) -> sqlite3.Row | None:
    with _connect() as conn:
        return conn.execute(
            "SELECT id, title, agent_id, model, project_id, created_at, updated_at "
            "FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()


def list_conversations(project_id: int | None = None) -> list[sqlite3.Row]:
    with _connect() as conn:
        cols = "id, title, agent_id, model, project_id, created_at, updated_at"
        if project_id is None:
            return conn.execute(
                f"SELECT {cols} FROM conversations WHERE project_id IS NULL ORDER BY updated_at DESC"
            ).fetchall()
        return conn.execute(
            f"SELECT {cols} FROM conversations WHERE project_id = ? ORDER BY updated_at DESC",
            (project_id,),
        ).fetchall()


# --- messages ------------------------------------------------------------

def add_message(
    conversation_id: int,
    role: str,
    content: str | None,
    tool_calls: list[dict] | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, tool_calls, tool_call_id, tool_name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                role,
                content,
                json.dumps(tool_calls) if tool_calls else None,
                tool_call_id,
                tool_name,
            ),
        )
    touch_conversation(conversation_id)


def get_conversation_messages(conversation_id: int) -> list[dict]:
    """Returns messages in the exact shape expected by Ollama's /api/chat."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content, tool_calls, tool_call_id FROM messages "
            "WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
    messages = []
    for row in rows:
        msg: dict = {"role": row["role"], "content": row["content"] or ""}
        if row["tool_calls"]:
            msg["tool_calls"] = json.loads(row["tool_calls"])
        if row["tool_call_id"]:
            msg["tool_call_id"] = row["tool_call_id"]
        messages.append(msg)
    return messages


# --- facts -----------------------------------------------------------------

def remember_fact(category: str, key: str, value: str, source: str = "user", conversation_id: int | None = None) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO facts (category, key, value, source, conversation_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(category, key) DO UPDATE SET
                value = excluded.value,
                source = excluded.source,
                updated_at = datetime('now')
            """,
            (category, key, value, source, conversation_id),
        )


def recall_facts(category: str | None = None) -> list[sqlite3.Row]:
    with _connect() as conn:
        if category:
            return conn.execute(
                "SELECT * FROM facts WHERE category = ? ORDER BY updated_at DESC", (category,)
            ).fetchall()
        return conn.execute("SELECT * FROM facts ORDER BY updated_at DESC").fetchall()


def delete_fact(fact_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))


def delete_all_facts() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM facts")


def delete_all_conversations() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM conversations")


def delete_conversation(conversation_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))


# --- app settings (theme, font size, etc.) ------------------------------------

def get_setting(key: str, default: str | None = None) -> str | None:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
