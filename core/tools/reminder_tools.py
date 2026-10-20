from __future__ import annotations

from datetime import datetime

from core import reminders
from core.tools import Tool, register

_NOTE_PREVIEW_CHARS = 400


def set_reminder(message: str, when: str, repeat: str = "none") -> dict:
    if repeat not in ("none", "daily", "weekly"):
        return {"error": "repeat must be one of: none, daily, weekly"}
    try:
        due_at = reminders.parse_when(when)
    except ValueError:
        return {"error": "when must be local time formatted as 'YYYY-MM-DD HH:MM'"}
    if due_at <= datetime.now() and repeat == "none":
        return {"error": "that time is already in the past - check the current date and time"}
    return reminders.add_reminder(message, due_at, repeat)


def add_note(title: str, body: str = "") -> dict:
    if not title.strip():
        return {"error": "a note needs a title"}
    return reminders.add_note(title.strip(), body.strip())


def list_reminders() -> dict:
    notes = [
        {"id": n["id"], "title": n["title"],
         "body": n["body"][:_NOTE_PREVIEW_CHARS] + ("…" if len(n["body"]) > _NOTE_PREVIEW_CHARS else "")}
        for n in reminders.list_notes()
    ]
    return {"reminders": reminders.list_pending(), "notes": notes}


def cancel_reminder(reminder_id: int | None = None, match: str | None = None) -> dict:
    """Cancel by id, or by words from the reminder/note so nobody needs an id."""
    if reminder_id is None and not (match or "").strip():
        return {"error": "give either match (words from the reminder or note) or reminder_id"}
    if reminder_id is not None:
        if reminders.cancel_reminder(int(reminder_id)):
            return {"cancelled": int(reminder_id)}
        return {"error": f"no pending reminder or note with id {reminder_id}; call list_reminders to see the valid ids, "
                         "or pass match with words from it"}
    found = reminders.find_pending(match)
    if not found:
        return {"error": f"nothing pending matches '{match}'; call list_reminders to see what exists"}
    if len(found) > 1:
        return {"error": "several items match, ask the user which one", "matches": [
            {"id": f["id"], "kind": f["kind"], "text": f["message"], "due_at": f["due_at"] or None} for f in found]}
    reminders.cancel_reminder(found[0]["id"])
    return {"cancelled": found[0]["id"], "kind": found[0]["kind"], "text": found[0]["message"]}


register(Tool(
    name="set_reminder",
    description=(
        "Schedule a reminder that notifies the user at a specific time, even if the app is closed. "
        "Use get_current_time first to resolve relative times like 'tomorrow at 9'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "What to remind the user about"},
            "when": {"type": "string", "description": "Local date and time, format 'YYYY-MM-DD HH:MM'"},
            "repeat": {"type": "string", "enum": ["none", "daily", "weekly"], "description": "Recurrence, default none"},
        },
        "required": ["message", "when"],
    },
    func=set_reminder,
))

register(Tool(
    name="add_note",
    description=(
        "Save a note for the user: a short title plus an optional longer body. Notes have no date and never "
        "notify; use set_reminder instead when the user wants to be alerted at a specific time."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short title of the note"},
            "body": {"type": "string", "description": "The note's content (can be long)"},
        },
        "required": ["title"],
    },
    func=add_note,
))

register(Tool(
    name="list_reminders",
    description="List the user's pending reminders and saved notes, with their ids.",
    parameters={"type": "object", "properties": {}, "required": []},
    func=list_reminders,
))

register(Tool(
    name="cancel_reminder",
    description=(
        "Cancel a pending reminder or delete a note. Pass match with a few words from its text or title "
        "(preferred, e.g. 'imprenta'); reminder_id also works if you already know it from list_reminders. "
        "If several items match, the result lists them so you can ask the user which one."
    ),
    parameters={
        "type": "object",
        "properties": {
            "match": {"type": "string", "description": "Words from the reminder's text or the note's title/body"},
            "reminder_id": {"type": "integer", "description": "Exact id, only if known"},
        },
        "required": [],
    },
    func=cancel_reminder,
))
