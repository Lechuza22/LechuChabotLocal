from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

from config import DATA_DIR

REMINDERS_DB = DATA_DIR / "reminders.db"
TIME_FORMAT = "%Y-%m-%d %H:%M"
REPEAT_STEPS = {"daily": timedelta(days=1), "weekly": timedelta(weeks=1)}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    due_at TEXT NOT NULL,
    repeat TEXT NOT NULL DEFAULT 'none',
    status TEXT NOT NULL DEFAULT 'pending'
)
"""


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(REMINDERS_DB)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def parse_when(value: str) -> datetime:
    """Local naive time, 'YYYY-MM-DD HH:MM' (a 'T' separator is accepted too)."""
    return datetime.strptime(value.strip().replace("T", " ")[:16], TIME_FORMAT)


def add_reminder(message: str, due_at: datetime, repeat: str = "none") -> dict:
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO reminders (message, due_at, repeat) VALUES (?, ?, ?)",
            (message, due_at.strftime(TIME_FORMAT), repeat),
        )
        return {"id": cur.lastrowid, "message": message,
                "due_at": due_at.strftime(TIME_FORMAT), "repeat": repeat}


def list_pending() -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, message, due_at, repeat FROM reminders "
            "WHERE status = 'pending' ORDER BY due_at"
        ).fetchall()
    return [dict(r) for r in rows]


def cancel_reminder(reminder_id: int) -> bool:
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
            (reminder_id,),
        )
        return cur.rowcount > 0


def pop_due(now: datetime) -> list[dict]:
    """Return reminders due at or before `now` and advance them: one-shot ones
    are marked fired, repeating ones are rescheduled to the next future slot
    (so a Mac that slept through several days fires once, not once per miss)."""
    due: list[dict] = []
    with closing(_connect()) as conn, conn:
        rows = conn.execute(
            "SELECT id, message, due_at, repeat FROM reminders "
            "WHERE status = 'pending' AND due_at <= ?",
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
