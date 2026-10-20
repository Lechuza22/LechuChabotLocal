"""Persistent chat conversations for LechuPasto (its own SQLite file, so they
never show up in Lechu's history). Messages are stored as the exact dicts the
model loop uses (user / assistant with tool_calls / tool); the system prompt is
rebuilt on every turn and never stored."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime

from config import DATA_DIR

CHATS_DB = DATA_DIR / "pasto_chats.db"
TITLE_CHARS = 32

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT 'Nuevo chat',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_open INTEGER NOT NULL DEFAULT 1,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    payload TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CHATS_DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    if "title_manual" not in {row["name"] for row in conn.execute("PRAGMA table_info(conversations)")}:
        conn.execute("ALTER TABLE conversations ADD COLUMN title_manual INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_chat() -> int:
    with closing(_connect()) as conn, conn:
        cur = conn.execute("INSERT INTO conversations (created_at, updated_at) VALUES (?, ?)", (_now(), _now()))
        return cur.lastrowid


def open_chats() -> list[dict]:
    """Tabs to show, oldest first (stable tab order)."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, title FROM conversations WHERE is_open = 1 AND deleted = 0 ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def archived_chats(limit: int = 30) -> list[dict]:
    """Closed (not deleted) chats with at least one message, newest first."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT c.id, c.title, c.updated_at FROM conversations c WHERE c.is_open = 0 AND c.deleted = 0 "
            "AND EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id) "
            "ORDER BY c.updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def load_messages(chat_id: int) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT payload FROM messages WHERE conversation_id = ? ORDER BY id", (chat_id,)).fetchall()
    return [json.loads(r["payload"]) for r in rows]


def append_messages(chat_id: int, messages: list[dict]) -> None:
    if not messages:
        return
    with closing(_connect()) as conn, conn:
        conn.executemany(
            "INSERT INTO messages (conversation_id, payload) VALUES (?, ?)",
            [(chat_id, json.dumps(m, ensure_ascii=False)) for m in messages],
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (_now(), chat_id))


def set_title_from(chat_id: int, text: str) -> str:
    title = " ".join(text.split())[:TITLE_CHARS].strip() or "Nuevo chat"
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, chat_id))
    return title


def rename_chat(chat_id: int, title: str) -> str:
    """User-chosen title: from then on the automatic summary never replaces it."""
    title = " ".join(title.split())[:60].strip() or "Nuevo chat"
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE conversations SET title = ?, title_manual = 1 WHERE id = ?", (title, chat_id))
    return title


def set_auto_title(chat_id: int, title: str) -> str | None:
    """Apply a generated title unless the user already named the chat. Returns
    the stored title, or None when it was left alone."""
    title = " ".join(title.split())[:60].strip()
    if not title:
        return None
    with closing(_connect()) as conn, conn:
        cur = conn.execute("UPDATE conversations SET title = ? WHERE id = ? AND title_manual = 0", (title, chat_id))
        return title if cur.rowcount else None


def close_chat(chat_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE conversations SET is_open = 0 WHERE id = ?", (chat_id,))


def reopen_chat(chat_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE conversations SET is_open = 1 WHERE id = ?", (chat_id,))


def delete_chat(chat_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE conversations SET deleted = 1, is_open = 0 WHERE id = ?", (chat_id,))
