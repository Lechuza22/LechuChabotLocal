from __future__ import annotations

from datetime import datetime

from googleapiclient.discovery import build

from core.google_auth import get_credentials
from core.tools import Tool, register

_NOT_CONNECTED = {
    "error": "Calendar no está conectado. Pedile al usuario que lo conecte en Configuración → Conexiones → Google."
}

# Google's named event colors (Calendar API colorId 1-11), mapped from common
# Spanish color words so the model can pass a plain color name instead of a
# numeric id it has no reason to know.
_COLOR_IDS = {
    "lavanda": "1",
    "salvia": "2",
    "uva": "3", "violeta": "3", "morado": "3", "purpura": "3", "púrpura": "3",
    "flamenco": "4", "rosa": "4",
    "banana": "5", "amarillo": "5",
    "mandarina": "6", "naranja": "6",
    "pavo real": "7", "celeste": "7", "turquesa": "7",
    "grafito": "8", "gris": "8",
    "arandano": "9", "arándano": "9", "azul": "9",
    "albahaca": "10", "verde": "10",
    "tomate": "11", "rojo": "11",
}


def _resolve_color(color: str | None) -> str | None:
    return _COLOR_IDS.get(color.strip().lower()) if color else None


def _to_rfc3339(value: str, end_of_day: bool = False) -> str:
    if "T" not in value:
        return f"{value}T23:59:59{_local_offset()}" if end_of_day else f"{value}T00:00:00{_local_offset()}"
    # A bare "T..." datetime with no offset/Z gets rejected by the Calendar
    # API - happened in testing (the model omitted it, the call silently
    # failed and it had to retry). Assume the machine's local timezone.
    tail = value[10:]
    if tail.endswith("Z") or "+" in tail or "-" in tail:
        return value
    return value + _local_offset()


def _local_offset() -> str:
    offset = datetime.now().astimezone().strftime("%z")  # e.g. "-0300"
    return f"{offset[:3]}:{offset[3:]}"


def list_calendar_events(start: str, end: str) -> dict:
    credentials = get_credentials()
    if credentials is None:
        return _NOT_CONNECTED
    service = build("calendar", "v3", credentials=credentials)
    result = service.events().list(
        calendarId="primary",
        timeMin=_to_rfc3339(start),
        timeMax=_to_rfc3339(end, end_of_day=True),
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    events = [
        {
            "id": e["id"],
            "title": e.get("summary"),
            "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
            "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
            "location": e.get("location"),
        }
        for e in result.get("items", [])
    ]
    return {"results": events}


def manage_calendar_event(
    action: str,
    event_id: str | None = None,
    title: str | None = None,
    start: str | None = None,
    end: str | None = None,
    color: str | None = None,
    attendees: list[str] | None = None,
) -> dict:
    credentials = get_credentials()
    if credentials is None:
        return _NOT_CONNECTED
    service = build("calendar", "v3", credentials=credentials)
    color_id = _resolve_color(color)

    if action == "create":
        if not (title and start and end):
            return {"error": "Para crear un evento hacen falta title, start y end."}
        body = {
            "summary": title,
            "start": {"dateTime": _to_rfc3339(start)},
            "end": {"dateTime": _to_rfc3339(end)},
        }
        if color_id:
            body["colorId"] = color_id
        if attendees:
            body["attendees"] = [{"email": email} for email in attendees]
        created = service.events().insert(calendarId="primary", body=body, sendUpdates="all").execute()
        return {"id": created["id"], "created": True}

    if not event_id:
        return {"error": f"Para {action} un evento hace falta event_id."}

    if action == "delete":
        service.events().delete(calendarId="primary", eventId=event_id, sendUpdates="all").execute()
        return {"id": event_id, "deleted": True}

    if action == "update":
        body = {}
        if title:
            body["summary"] = title
        if start:
            body["start"] = {"dateTime": _to_rfc3339(start)}
        if end:
            body["end"] = {"dateTime": _to_rfc3339(end)}
        if color_id:
            body["colorId"] = color_id
        if attendees:
            body["attendees"] = [{"email": email} for email in attendees]
        updated = service.events().patch(calendarId="primary", eventId=event_id, body=body, sendUpdates="all").execute()
        return {"id": updated["id"], "updated": True}

    return {"error": f"Acción desconocida '{action}'. Usá create, update o delete."}


register(Tool(
    name="list_calendar_events",
    description="List events in the connected Google Calendar between two dates.",
    parameters={
        "type": "object",
        "properties": {
            "start": {"type": "string", "description": "Start date/datetime, e.g. '2026-08-06' or RFC3339"},
            "end": {"type": "string", "description": "End date/datetime, e.g. '2026-08-13' or RFC3339"},
        },
        "required": ["start", "end"],
    },
    func=list_calendar_events,
))

register(Tool(
    name="manage_calendar_event",
    description="Create, update, or delete a Google Calendar event. Requires user confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "update", "delete"]},
            "event_id": {"type": "string", "description": "Required for update/delete"},
            "title": {"type": "string", "description": "Event title, required for create"},
            "start": {"type": "string", "description": "Start datetime, required for create"},
            "end": {"type": "string", "description": "End datetime, required for create"},
            "color": {
                "type": "string",
                "description": (
                    "Optional event color. If the user doesn't specify one when creating an event, ask them to "
                    "pick from: azul, rojo, verde, amarillo, naranja, morado, rosa, gris, turquesa, lavanda, banana"
                ),
            },
            "attendees": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of guest email addresses to invite to the event",
            },
        },
        "required": ["action"],
    },
    func=manage_calendar_event,
    requires_confirmation=True,
))
