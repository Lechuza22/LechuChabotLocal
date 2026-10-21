from __future__ import annotations

import base64
import re
from email.mime.text import MIMEText

from googleapiclient.discovery import build

from core.google_auth import get_credentials
from core.tools import Tool, register

_NOT_CONNECTED = {
    "error": "Gmail no está conectado. Pedile al usuario que lo conecte en Configuración → Conexiones → Google."
}


def _get_header(headers: list[dict], name: str) -> str | None:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return None


def _extract_body(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        text = _extract_body(part)
        if text:
            return text
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    return ""


def _attachments(payload: dict) -> list[dict]:
    """Named parts of the message (attached or inline files), at any depth."""
    found = []
    for part in payload.get("parts", []) or []:
        if part.get("filename"):
            found.append({"name": part["filename"], "type": part.get("mimeType", "")})
        found.extend(_attachments(part))
    return found


def search_emails(query: str, max_results: int = 10) -> dict:
    credentials = get_credentials()
    if credentials is None:
        return _NOT_CONNECTED
    service = build("gmail", "v1", credentials=credentials)
    result = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    items = []
    for m in result.get("messages", []):
        detail = service.users().messages().get(
            userId="me", id=m["id"], format="metadata", metadataHeaders=["Subject", "From", "Date"]
        ).execute()
        headers = detail.get("payload", {}).get("headers", [])
        items.append({
            "id": m["id"],
            "subject": _get_header(headers, "Subject"),
            "from": _get_header(headers, "From"),
            "date": _get_header(headers, "Date"),
            "snippet": detail.get("snippet"),
        })
    return {"results": items}


def read_email(message_id: str) -> dict:
    credentials = get_credentials()
    if credentials is None:
        return _NOT_CONNECTED
    service = build("gmail", "v1", credentials=credentials)
    detail = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    headers = detail.get("payload", {}).get("headers", [])
    return {
        "id": message_id,
        "subject": _get_header(headers, "Subject"),
        "from": _get_header(headers, "From"),
        "to": _get_header(headers, "To"),
        "date": _get_header(headers, "Date"),
        "body": _extract_body(detail.get("payload", {})),
        "attachments": _attachments(detail.get("payload", {})),
    }


def find_email_details(query: str, max_results: int = 1) -> dict:
    """Search + read in one step, so nobody has to know a message id: the full
    text of the best matches plus the Google files they link to (with their
    open comments)."""
    from datetime import datetime

    from core import mail_context

    # The model sometimes asks for "id:<hex>" after seeing ids in search results.
    by_id = re.fullmatch(r"(?:id:)?([0-9a-f]{12,})", query.strip())
    if by_id:
        found = {"results": [{"id": by_id.group(1)}]}
    else:
        found = search_emails(query, max(1, min(int(max_results), 3)))
    if "error" in found:
        return found
    if not found["results"]:
        return {"error": "No encontré mails con esa búsqueda. Probá con otras palabras (remitente, asunto o tema)."}
    digest = mail_context.build_digest(found["results"], datetime.now().astimezone(), body_limit=4000)
    if digest is None:
        return _NOT_CONNECTED
    return digest


def send_email(to: str, subject: str, body: str) -> dict:
    credentials = get_credentials()
    if credentials is None:
        return _NOT_CONNECTED
    service = build("gmail", "v1", credentials=credentials)
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return {"id": sent["id"], "sent": True}


register(Tool(
    name="search_emails",
    description=(
        "Search Gmail messages using Gmail's search syntax. Examples: 'from:someone subject:invoice'; "
        "emails received today or in the last day: 'newer_than:1d'; last week: 'newer_than:7d'; "
        "unread: 'is:unread'; on a date: 'after:2026/10/19 before:2026/10/20'. "
        "To list recent mail without filters use 'in:inbox'. Never invent operators like 'from:today'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail search query"},
            "max_results": {"type": "integer", "description": "Max results to return, defaults to 10"},
        },
        "required": ["query"],
    },
    func=search_emails,
))

register(Tool(
    name="read_email",
    description="Read the full subject, sender, and body of a Gmail message by its id (from search_emails results).",
    parameters={
        "type": "object",
        "properties": {"message_id": {"type": "string", "description": "Gmail message id"}},
        "required": ["message_id"],
    },
    func=read_email,
))

register(Tool(
    name="find_email_details",
    description=(
        "Find an email by what the user says about it (sender, subject, topic) and return its full text plus the "
        "Google Docs/Sheets it links to, with their open comments. Use it whenever the user asks to explain, detail "
        "or read an email. Examples of query: 'from:maria budget' (a topic from a sender), 'in:inbox' with "
        "max_results 1 (the latest email), 'subject:convivencia'. If the email contains pictures the result says how many ('images'): you cannot read pictures, say so plainly. NEVER ask the user for an email id."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail search query built from what the user described"},
            "max_results": {"type": "integer", "description": "How many matching emails to read (1-3), default 1"},
        },
        "required": ["query"],
    },
    func=find_email_details,
))

register(Tool(
    name="send_email",
    description="Send an email from the connected Gmail account. Requires user confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject"},
            "body": {"type": "string", "description": "Plain text email body"},
        },
        "required": ["to", "subject", "body"],
    },
    func=send_email,
    requires_confirmation=True,
))
