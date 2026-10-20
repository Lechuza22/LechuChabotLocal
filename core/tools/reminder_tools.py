from __future__ import annotations

from core import reminders
from core.tools import Tool, register


def set_reminder(message: str, when: str, repeat: str = "none") -> dict:
    if repeat not in ("none", "daily", "weekly"):
        return {"error": "repeat must be one of: none, daily, weekly"}
    try:
        due_at = reminders.parse_when(when)
    except ValueError:
        return {"error": "when must be local time formatted as 'YYYY-MM-DD HH:MM'"}
    from datetime import datetime
    if due_at <= datetime.now() and repeat == "none":
        return {"error": "that time is already in the past - check the current time with get_current_time"}
    return reminders.add_reminder(message, due_at, repeat)


def list_reminders() -> dict:
    return {"reminders": reminders.list_pending()}


def cancel_reminder(reminder_id: int) -> dict:
    if reminders.cancel_reminder(int(reminder_id)):
        return {"cancelled": int(reminder_id)}
    return {"error": f"no pending reminder with id {reminder_id}"}


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
    name="list_reminders",
    description="List the user's pending reminders with their ids and times.",
    parameters={"type": "object", "properties": {}, "required": []},
    func=list_reminders,
))

register(Tool(
    name="cancel_reminder",
    description="Cancel a pending reminder by its id (from list_reminders).",
    parameters={
        "type": "object",
        "properties": {"reminder_id": {"type": "integer", "description": "Reminder id"}},
        "required": ["reminder_id"],
    },
    func=cancel_reminder,
))
