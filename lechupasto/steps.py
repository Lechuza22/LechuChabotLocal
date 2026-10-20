"""Catalog of pipeline steps a task can use. Steps fetch data in plain code;
only `llm_summarize_digest` touches the local model (see the reliability
findings in project memory: code gathers, the model writes)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from typing import Callable

import httpx

from config import CONFIG
from core import briefing, mail_context, reminders

logger = logging.getLogger(__name__)

MODEL = "qwen3:8b"
NUM_CTX = 8192
MAX_PROMPT_DATA_CHARS = 18000  # ~6k tokens of the 8k window, leaving room for the answer


def calendar_events(now: datetime, params: dict, ctx: dict):
    return briefing.fetch_events(now)  # list | None when Google is unavailable


def emails(now: datetime, params: dict, ctx: dict):
    return briefing.fetch_emails(now)  # list | None


UNREAD_LOOKBACK_DAYS = 7
UNREAD_FETCH = 30


def _sender_name(header: str | None) -> str:
    name, address = parseaddr(header or "")
    return name or address or "?"


def unread_older(now: datetime, params: dict, ctx: dict):
    """Still-unread inbox mail from the week before the summarized window.
    Listed by code (sender, subject, date): no model, and nothing is marked as read."""
    from core.tools.gmail_tools import search_emails

    window_start, _ = briefing._email_window(now)
    since = window_start - timedelta(days=UNREAD_LOOKBACK_DAYS)
    query = (f"in:inbox is:unread after:{int(since.timestamp())} before:{int(window_start.timestamp())} "
             "-category:promotions -category:social")
    result = briefing._google_call(search_emails, query, UNREAD_FETCH)
    if result is None or "error" in result:
        return None
    items = []
    for hit in result["results"]:
        try:
            date = parsedate_to_datetime(hit["date"]).astimezone().strftime("%d/%m")
        except (TypeError, ValueError):
            date = ""
        items.append({"from": _sender_name(hit.get("from")), "subject": hit.get("subject") or "(sin asunto)", "date": date})
    return items


def today_items(now: datetime, params: dict, ctx: dict):
    """Reminders still pending for today (earlier ones already fired) and the
    user's saved notes. Falsy when there is nothing, so the section hides."""
    upcoming = reminders.due_today(now)
    notes = reminders.list_notes()
    if not upcoming and not notes:
        return {}
    return {"reminders": upcoming, "notes": notes}


def email_digest(now: datetime, params: dict, ctx: dict):
    """Full message text + linked Drive files (content and open comments)."""
    source = ctx.get(params["input"])
    if source is None:
        return None
    if not source:
        return {"emails": [], "docs": []}
    return mail_context.build_digest(source, now.astimezone())


def commented_docs(now: datetime, params: dict, ctx: dict):
    digest = ctx.get(params["input"])
    if digest is None:
        return None
    return [d for d in digest["docs"] if d.get("comments")]


def _prompt_data(digest: dict) -> str:
    def build(body_limit: int, doc_limit: int) -> str:
        return json.dumps({
            "mails": [{"de": e["from"], "asunto": e["subject"], "mensaje": e["message"][:body_limit],
                       "documentos": e["documents"]} for e in digest["emails"]],
            "documentos": [{
                "titulo": d["name"], "tipo": d["kind"],
                # Only documents with open comments get their text: the 8B model
                # tends to present a document's own text as if it were comments.
                **({"contenido_inicial_del_documento": d.get("extract", "")[:doc_limit]} if d.get("comments") else {}),
                "comentarios_abiertos": [{"autor": c["author"], "fecha": c["date"], "texto": c["text"],
                                          "ultima_respuesta": c["last_reply"]} for c in d["comments"]],
            } for d in digest["docs"]],
        }, ensure_ascii=False)

    for body_limit, doc_limit in ((1200, 1500), (600, 700), (300, 300)):
        data = build(body_limit, doc_limit)
        if len(data) <= MAX_PROMPT_DATA_CHARS:
            break
    return data


def _plain_fallback(digest: dict) -> str:
    lines = [f"- {e['from']}: {e['subject']}" for e in digest["emails"]]
    lines += [f"- {d['name']}: {len(d['comments'])} comentarios abiertos" for d in digest["docs"] if d.get("comments")]
    return "\n".join(lines)


def llm_summarize_digest(now: datetime, params: dict, ctx: dict):
    digest = ctx.get(params["input"])
    if digest is None:
        return None
    if not digest["emails"]:
        return ""
    prompt = (
        f"Estos son los {len(digest['emails'])} mails que recibí ayer, con su texto completo y los "
        "documentos de Google a los que enlazan (con sus comentarios abiertos recientes). "
        "Escribí un resumen en español rioplatense, hablándome de vos (por ejemplo: \"te pidió\", "
        "\"te compartió\"). Reglas: una viñeta por tema o conversación, juntando los mails de la "
        "misma conversación. Cada viñeta: quién, qué pasó y, si corresponde, qué tengo que hacer yo. "
        "Si un documento tiene comentarios abiertos, dedicale UNA sola viñeta por documento (no una por "
        "comentario) que resuma qué se pregunta o se pide en todos esos comentarios y a quién, "
        "mencionando el título. Si varios mails piden lo mismo, es UNA sola viñeta. Poné primero lo que "
        "requiera una acción mía. Máximo 6 viñetas, sin emojis. Usá solo lo que está en los datos: no "
        "agregues cargos, teléfonos ni detalles que no figuren. Solo hablá de \"comentarios\" cuando estén "
        "en comentarios_abiertos; el contenido_inicial_del_documento es solo contexto, no son comentarios.\n\n" + _prompt_data(digest)
    )
    try:
        resp = httpx.post(
            f"{CONFIG.ollama_base_url}/api/chat",
            json={"model": MODEL, "stream": False, "think": False,
                  "options": {"num_ctx": NUM_CTX, "temperature": 0.3},
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=240.0,
        )
        resp.raise_for_status()
        text = resp.json()["message"]["content"].strip()
        if text:
            return text
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.warning("digest summary via Ollama failed (%s), using plain list", type(exc).__name__)
    return _plain_fallback(digest)


STEP_CATALOG: dict[str, Callable] = {
    "calendar_events": calendar_events,
    "emails": emails,
    "today_items": today_items,
    "unread_older": unread_older,
    "email_digest": email_digest,
    "commented_docs": commented_docs,
    "llm_summarize_digest": llm_summarize_digest,
}
