from __future__ import annotations

from datetime import datetime

from core import agenda
from core.tools import Tool, register


def add_calendar_event(title: str, start: str, duration_minutes: int = agenda.DEFAULT_MINUTES,
                       location: str | None = None, notes: str | None = None) -> dict:
    try:
        start_dt = datetime.strptime(start.strip().replace("T", " ")[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return {"error": "start must be local time formatted as 'YYYY-MM-DD HH:MM'"}
    if start_dt < datetime.now():
        return {"error": "that time is already in the past - check the current date and time"}
    try:
        return agenda.create_event(title.strip(), start_dt, max(5, int(duration_minutes)), location, notes)
    except agenda.NotConnected:
        return {"error": "Google no está conectado. Conectalo desde Lechu: Configuración > Conexiones."}


register(Tool(
    name="add_calendar_event",
    description=(
        "Schedule an event in the user's Google Calendar (use this when the user says 'agendame', 'agendá' or asks "
        "for a meeting/appointment; for a simple alert use set_reminder instead). The user is always invited "
        "automatically; never pass guests. Requires user confirmation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Event title"},
            "start": {"type": "string", "description": "Local start date and time, format 'YYYY-MM-DD HH:MM'"},
            "duration_minutes": {"type": "integer", "description": "Length in minutes, default 60"},
            "location": {"type": "string", "description": "Place, optional"},
            "notes": {"type": "string", "description": "Description, optional"},
        },
        "required": ["title", "start"],
    },
    func=add_calendar_event,
    requires_confirmation=True,
))
