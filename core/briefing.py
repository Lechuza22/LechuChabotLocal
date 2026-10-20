from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

import httpx

from config import CONFIG, DATA_DIR

logger = logging.getLogger(__name__)

STATE_PATH = DATA_DIR / "briefing_state.json"
SEND_HOUR = 9
MODEL = "qwen3:8b"
MAX_EMAILS = 25
TELEGRAM_LIMIT = 3800  # API caps messages at 4096 chars

_WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
           "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def is_due(now: datetime) -> bool:
    """Mon-Fri, 09:00 or later, and not already sent today - so a Mac that
    was asleep/off at 09:00 sends as soon as it's back."""
    return now.weekday() < 5 and now.hour >= SEND_HOUR and _last_sent() != now.date().isoformat()


def _last_sent() -> str | None:
    try:
        return json.loads(STATE_PATH.read_text()).get("last_sent")
    except (OSError, ValueError):
        return None


def mark_sent(now: datetime) -> None:
    STATE_PATH.write_text(json.dumps({"last_sent": now.date().isoformat()}))


def _email_window(now: datetime) -> tuple[datetime, datetime]:
    """Yesterday 00:00 -> today 00:00. On Monday it starts Saturday 00:00 so
    weekend mail isn't lost (Sunday alone would skip Saturday)."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=2 if now.weekday() == 0 else 1), today


def _google_call(func, *args) -> dict | None:
    """None when Google can't be used - not connected, or the saved token was
    revoked/expired (RefreshError, e.g. OAuth apps in 'Testing' mode expire
    refresh tokens after 7 days). Never raises: the briefing must still go out."""
    try:
        return func(*args)
    except Exception as exc:  # noqa: BLE001 - any Google/network failure degrades the same way
        logger.warning("Google call %s failed: %s", func.__name__, type(exc).__name__)
        return None


def fetch_emails(now: datetime) -> list[dict] | None:
    from core.tools.gmail_tools import search_emails

    start, end = _email_window(now)
    query = (f"in:inbox after:{int(start.timestamp())} before:{int(end.timestamp())} "
             "-category:promotions -category:social")
    result = _google_call(search_emails, query, MAX_EMAILS)
    return None if result is None or "error" in result else result["results"]


def fetch_events(now: datetime) -> list[dict] | None:
    from core.tools.calendar_tools import list_calendar_events

    day = now.strftime("%Y-%m-%d")
    result = _google_call(list_calendar_events, day, day)
    return None if result is None or "error" in result else result["results"]


def _format_event(event: dict) -> str:
    start = event.get("start") or ""
    when = start[11:16] if "T" in start else "todo el día"
    place = f" ({event['location']})" if event.get("location") else ""
    return f"- {when}  {event.get('title') or '(sin título)'}{place}"


def _plain_emails(emails: list[dict]) -> str:
    return "\n".join(f"- {e.get('from') or '?'}: {e.get('subject') or '(sin asunto)'}" for e in emails)


def summarize_emails(emails: list[dict]) -> str:
    """Local-model summary; falls back to a plain sender/subject list if
    Ollama is down or answers nothing usable."""
    items = [{"de": e.get("from"), "asunto": e.get("subject"), "extracto": e.get("snippet")} for e in emails]
    prompt = (
        f"Estos son {len(emails)} mails que recibí ayer. Escribí un resumen en español "
        "rioplatense, hablándome de vos (por ejemplo: \"te pidió\", \"te compartió\"). "
        f"Reglas: una viñeta por tema o conversación, nunca más de {len(emails)} viñetas "
        "en total; si dos mails son de la misma conversación, juntalos en una sola. "
        "Cada viñeta: quién, qué pasó y, si corresponde, qué tengo que hacer yo. "
        "Poné primero lo que requiera una acción mía. Sin emojis. Usá solo lo que "
        "está en los datos: no agregues cargos, teléfonos ni detalles que no figuren "
        "en el asunto o el extracto.\n\n"
        + json.dumps(items, ensure_ascii=False)
    )
    try:
        resp = httpx.post(
            f"{CONFIG.ollama_base_url}/api/chat",
            json={"model": MODEL, "stream": False, "think": False,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=120.0,
        )
        resp.raise_for_status()
        text = resp.json()["message"]["content"].strip()
        if text:
            return text
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("email summary via Ollama failed (%s), using plain list", type(exc).__name__)
    return _plain_emails(emails)


def build_briefing(now: datetime) -> str:
    header = f"Buen día. Resumen del {_WEEKDAYS[now.weekday()]} {now.day} de {_MONTHS[now.month - 1]}"

    events = fetch_events(now)
    if events is None:
        agenda = "No pude leer el calendario: reconectá Google en Lechu (Configuración > Conexiones)."
    elif not events:
        agenda = "Sin eventos hoy."
    else:
        agenda = "\n".join(_format_event(e) for e in events)

    emails = fetch_emails(now)
    if emails is None:
        mails = "No pude leer Gmail: reconectá Google en Lechu (Configuración > Conexiones)."
    elif not emails:
        mails = "Sin mails nuevos."
    else:
        mails = summarize_emails(emails)

    since = "el fin de semana" if now.weekday() == 0 else "ayer"
    text = f"{header}\n\nAgenda de hoy\n{agenda}\n\nMails de {since} ({len(emails or [])})\n{mails}"
    return text[:TELEGRAM_LIMIT]


if __name__ == "__main__":
    # Dry run: print what would be sent, don't send or mark as sent.
    print(build_briefing(datetime.now()))
