from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

from config import DATA_DIR

REMINDERS_DB = DATA_DIR / "reminders.db"
TIME_FORMAT = "%Y-%m-%d %H:%M"
REPEAT_STEPS = {"daily": timedelta(days=1), "weekly": timedelta(weeks=1)}

# One table for reminders and notes so both share an id space: a single
# cancel/delete-by-id works for either (keeps the chat agent's tool count low).
# A note is an item with kind='note', no due time, a title (message) and a body.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    due_at TEXT NOT NULL,
    repeat TEXT NOT NULL DEFAULT 'none',
    status TEXT NOT NULL DEFAULT 'pending'
)
"""
_MIGRATIONS = {
    "kind": "ALTER TABLE reminders ADD COLUMN kind TEXT NOT NULL DEFAULT 'reminder'",
    "body": "ALTER TABLE reminders ADD COLUMN body TEXT NOT NULL DEFAULT ''",
    "updated_at": "ALTER TABLE reminders ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''",
}


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(REMINDERS_DB)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(reminders)")}
    for column, ddl in _MIGRATIONS.items():
        if column not in existing:
            conn.execute(ddl)
    conn.commit()
    return conn


def _now_text() -> str:
    return datetime.now().strftime(TIME_FORMAT)


def parse_when(value: str) -> datetime:
    """Local naive time, 'YYYY-MM-DD HH:MM' (a 'T' separator is accepted too)."""
    return datetime.strptime(value.strip().replace("T", " ")[:16], TIME_FORMAT)


# --- reminders -------------------------------------------------------------

def add_reminder(message: str, due_at: datetime, repeat: str = "none") -> dict:
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO reminders (message, due_at, repeat, kind, updated_at) VALUES (?, ?, ?, 'reminder', ?)",
            (message, due_at.strftime(TIME_FORMAT), repeat, _now_text()),
        )
        return {"id": cur.lastrowid, "kind": "reminder", "message": message,
                "due_at": due_at.strftime(TIME_FORMAT), "repeat": repeat}


def list_pending() -> list[dict]:
    """Pending reminders (not notes), soonest first."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, message, due_at, repeat FROM reminders "
            "WHERE status = 'pending' AND kind = 'reminder' ORDER BY due_at"
        ).fetchall()
    return [dict(r) for r in rows]


def list_fired(limit: int = 15) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, message, due_at FROM reminders "
            "WHERE status = 'fired' AND kind = 'reminder' ORDER BY due_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def due_today(now: datetime) -> list[dict]:
    """Pending reminders due later today (earlier ones already fired)."""
    day = now.strftime("%Y-%m-%d")
    return [r for r in list_pending() if r["due_at"].startswith(day)]


def pop_due(now: datetime) -> list[dict]:
    """Return reminders due at or before `now` and advance them: one-shot ones
    are marked fired, repeating ones are rescheduled to the next future slot
    (so a Mac that slept through several days fires once, not once per miss).
    Notes never fire."""
    due: list[dict] = []
    with closing(_connect()) as conn, conn:
        rows = conn.execute(
            "SELECT id, message, due_at, repeat FROM reminders "
            "WHERE status = 'pending' AND kind = 'reminder' AND due_at <= ?",
            (now.strftime(TIME_FORMAT),),
        ).fetchall()
        for row in rows:
            due.append(dict(row))
            step = REPEAT_STEPS.get(row["repeat"])
            if step is None:
                conn.execute("UPDATE reminders SET status = 'fired' WHERE id = ?", (row["id"],))
                continue
            next_due = parse_when(row["due_at"]) + step
            while next_due <= now:
                next_due += step
            conn.execute(
                "UPDATE reminders SET due_at = ? WHERE id = ?",
                (next_due.strftime(TIME_FORMAT), row["id"]),
            )
    return due


# --- notes -----------------------------------------------------------------

def add_note(title: str, body: str = "") -> dict:
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO reminders (message, due_at, repeat, kind, body, updated_at) VALUES (?, '', 'none', 'note', ?, ?)",
            (title, body, _now_text()),
        )
        return {"id": cur.lastrowid, "kind": "note", "title": title, "body": body}


def update_note(note_id: int, title: str, body: str) -> bool:
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "UPDATE reminders SET message = ?, body = ?, updated_at = ? "
            "WHERE id = ? AND kind = 'note' AND status = 'pending'",
            (title, body, _now_text(), note_id),
        )
        return cur.rowcount > 0


def list_notes() -> list[dict]:
    """Active notes, most recently edited first."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, message AS title, body, updated_at FROM reminders "
            "WHERE status = 'pending' AND kind = 'note' ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# --- both ------------------------------------------------------------------

def cancel_reminder(item_id: int) -> bool:
    """Cancel a pending reminder or delete a note, by id."""
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
            (item_id,),
        )
        return cur.rowcount > 0


def find_pending(match: str) -> list[dict]:
    """Pending reminders and notes whose text/title contains `match` (case-insensitive)."""
    needle = f"%{match.strip().lower()}%"
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, kind, message, due_at FROM reminders WHERE status = 'pending' "
            "AND (lower(message) LIKE ? OR lower(body) LIKE ?) ORDER BY id", (needle, needle)
        ).fetchall()
    return [dict(r) for r in rows]


def signature() -> tuple:
    """Cheap change detector for UIs that poll (count + latest touch)."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(MAX(id), 0) AS last_id, "
            "COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) AS pending, "
            "COALESCE(MAX(updated_at), '') AS touched FROM reminders"
        ).fetchone()
    return tuple(row)
