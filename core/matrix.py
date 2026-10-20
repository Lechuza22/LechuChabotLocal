"""Priority matrix items (LechuPasto > Recordatorios > Matriz).

Stored in the same SQLite file as reminders and notes (data/reminders.db) so
there is a single place to back up. New items land in the "inbox" tray and are
dragged into one of four quadrants; position keeps the order inside each."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime

from core.reminders import REMINDERS_DB

QUADRANTS = {
    "inbox": "Sin clasificar",
    "urgent": "Urgente",
    "not_urgent": "No urgente",
    "postpone": "Postergar",
    "late": "Retrasado",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS matrix_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    quadrant TEXT NOT NULL DEFAULT 'inbox',
    position INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _connect() -> sqlite3.Connection:
    REMINDERS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(REMINDERS_DB)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def add_item(text: str, quadrant: str = "inbox") -> dict:
    if quadrant not in QUADRANTS:
        raise ValueError(f"unknown quadrant {quadrant!r}")
    with closing(_connect()) as conn, conn:
        last = conn.execute(
            "SELECT COALESCE(MAX(position), -1) FROM matrix_items WHERE status = 'open' AND quadrant = ?", (quadrant,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO matrix_items (text, quadrant, position, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (text.strip(), quadrant, last + 1, _now(), _now()),
        )
        return {"id": cur.lastrowid, "text": text.strip(), "quadrant": quadrant}


def list_open() -> dict[str, list[dict]]:
    """Open items grouped by quadrant, each in its dragged order."""
    grouped: dict[str, list[dict]] = {key: [] for key in QUADRANTS}
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, text, quadrant FROM matrix_items WHERE status = 'open' ORDER BY position, id"
        ).fetchall()
    for row in rows:
        grouped.setdefault(row["quadrant"], []).append(dict(row))
    return grouped


def set_order(quadrant: str, item_ids: list[int]) -> None:
    """Put exactly these items, in this order, into a quadrant (used after a drag)."""
    if quadrant not in QUADRANTS:
        raise ValueError(f"unknown quadrant {quadrant!r}")
    with closing(_connect()) as conn, conn:
        for position, item_id in enumerate(item_ids):
            conn.execute(
                "UPDATE matrix_items SET quadrant = ?, position = ?, updated_at = ? WHERE id = ? AND status = 'open'",
                (quadrant, position, _now(), item_id),
            )


def update_text(item_id: int, text: str) -> bool:
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "UPDATE matrix_items SET text = ?, updated_at = ? WHERE id = ? AND status = 'open'",
            (text.strip(), _now(), item_id),
        )
        return cur.rowcount > 0


def complete(item_id: int) -> bool:
    """Mark as done (kept in the database, hidden from the board)."""
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "UPDATE matrix_items SET status = 'done', updated_at = ? WHERE id = ? AND status = 'open'", (_now(), item_id)
        )
        return cur.rowcount > 0


def delete(item_id: int) -> bool:
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "UPDATE matrix_items SET status = 'deleted', updated_at = ? WHERE id = ? AND status = 'open'", (_now(), item_id)
        )
        return cur.rowcount > 0
