from __future__ import annotations

import base64
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
    }


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
    description="Search Gmail messages using Gmail's search syntax (e.g. 'from:someone subject:invoice').",
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
