"""Google Calendar helpers for LechuPasto's Agenda screen and the chat's
scheduling tool: read a month, create events (always inviting the user's own
address), delete events.

The invited address lives in the Keychain (`calendar_invite_email`), never in
the repo or a prompt, so the model can't change it."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from googleapiclient.discovery import build

from core.google_auth import get_credentials
from core.secrets import get_secret

logger = logging.getLogger(__name__)

INVITE_KEY = "calendar_invite_email"
DEFAULT_MINUTES = 60


class NotConnected(RuntimeError):
    pass


def invite_email() -> str | None:
    return get_secret(INVITE_KEY)


def _service():
    credentials = get_credentials()
    if credentials is None:
        raise NotConnected("Google no está conectado")
    return build("calendar", "v3", credentials=credentials)


def _local_iso(moment: datetime) -> str:
    """Naive datetimes are local time; the API wants an offset."""
    return moment.astimezone().isoformat(timespec="seconds")


def build_event_body(title: str, start: datetime, minutes: int = DEFAULT_MINUTES, location: str | None = None,
                     notes: str | None = None, invite: bool = True) -> dict:
    body: dict = {
        "summary": title,
        "start": {"dateTime": _local_iso(start)},
        "end": {"dateTime": _local_iso(start + timedelta(minutes=minutes))},
    }
    if location:
        body["location"] = location
    if notes:
        body["description"] = notes
    guest = invite_email() if invite else None
    if guest:
        body["attendees"] = [{"email": guest}]
    return body


def create_event(title: str, start: datetime, minutes: int = DEFAULT_MINUTES, location: str | None = None,
                 notes: str | None = None, invite: bool = True) -> dict:
    body = build_event_body(title, start, minutes, location, notes, invite)
    created = _service().events().insert(
        calendarId="primary", body=body, sendUpdates="all" if body.get("attendees") else "none"
    ).execute()
    return {"id": created["id"], "link": created.get("htmlLink"), "title": title,
            "start": body["start"]["dateTime"], "end": body["end"]["dateTime"],
            "invited": body["attendees"][0]["email"] if body.get("attendees") else None}


def delete_event(event_id: str) -> None:
    _service().events().delete(calendarId="primary", eventId=event_id, sendUpdates="all").execute()


def _parse(moment: dict) -> tuple[datetime | date, bool]:
    if "dateTime" in moment:
        return datetime.fromisoformat(moment["dateTime"]).astimezone().replace(tzinfo=None), False
    return date.fromisoformat(moment["date"]), True


def month_events(first: date, last: date) -> list[dict]:
    """Events overlapping [first, last] from the primary calendar, normalized
    for a grid: local naive datetimes; all-day events carry plain dates."""
    result = _service().events().list(
        calendarId="primary", singleEvents=True, orderBy="startTime", maxResults=250,
        timeMin=_local_iso(datetime.combine(first, datetime.min.time())),
        timeMax=_local_iso(datetime.combine(last + timedelta(days=1), datetime.min.time())),
        fields="items(id,summary,start,end,location,description,htmlLink,attendees(email),status)",
    ).execute()
    events = []
    for item in result.get("items", []):
        if item.get("status") == "cancelled":
            continue
        start, all_day = _parse(item["start"])
        end, _ = _parse(item.get("end", item["start"]))
        events.append({
            "id": item["id"], "title": item.get("summary") or "(sin título)", "start": start, "end": end,
            "all_day": all_day, "location": item.get("location"), "notes": item.get("description"),
            "link": item.get("htmlLink"), "guests": [a["email"] for a in item.get("attendees", [])],
        })
    return events


def days_of(event: dict) -> list[date]:
    """Every calendar day an event appears on (all-day events: end is exclusive)."""
    if event["all_day"]:
        days, day = [], event["start"]
        while day < event["end"]:
            days.append(day)
            day += timedelta(days=1)
        return days or [event["start"]]
    return [event["start"].date()]
