"""Turns raw Gmail search hits into something a summary can actually use:
the full (de-noised) message text, plus the Google Docs/Sheets/Slides linked
in it with their content and open comments.

The old summary used Gmail's ~200-char snippet, so it never saw the body of
long mails, the comment text in Google's notification mails, or the linked
documents themselves."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

from core.google_auth import get_credentials

logger = logging.getLogger(__name__)

MAX_BODY_CHARS = 1200
MAX_DOC_CHARS = 1500
MAX_DOCS = 6
COMMENT_WINDOW_DAYS = 14
MAX_COMMENTS_PER_DOC = 8
MAX_COMMENT_CHARS = 300

_FILE_URL = re.compile(
    r"https?://(?:docs|drive)\.google\.com/(?:(document|spreadsheets|presentation)/(?:u/\d+/)?d/|file/d/)([\w-]{20,})"
)
_REPLY_HEADER = re.compile(r"\n\s*(?:El|On)\s[^\n]{0,200}(?:\n[^\n]{0,200})?\s*(?:escribió|wrote)\s*:", re.IGNORECASE)
_NOISE_LINE = re.compile(r"^\s*(?:<?https?://\S+>?|\[image:[^\]]*\]|>.*)\s*$")
_MENTION = re.compile(r"@([\w.+-]+)@[\w.-]+\.\w+")  # Google comments write mentions as @user@domain
_KINDS = {"document": "Doc", "spreadsheets": "Hoja de cálculo", "presentation": "Presentación", None: "Archivo"}


def clean_body(text: str, limit: int = MAX_BODY_CHARS) -> str:
    """Drop quoted replies, bare links and image placeholders; collapse blanks."""
    match = _REPLY_HEADER.search("\n" + text)
    if match:
        text = ("\n" + text)[: match.start()]
    lines = [ln.strip() for ln in text.splitlines() if not _NOISE_LINE.match(ln)]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def _tidy_comment(text: str) -> str:
    return re.sub(r"\s+", " ", _MENTION.sub(r"@\1", text)).strip()


def extract_file_ids(body: str) -> list[tuple[str, str | None]]:
    """(file_id, kind) pairs in order of appearance, deduplicated."""
    seen: dict[str, str | None] = {}
    for kind, file_id in _FILE_URL.findall(body):
        seen.setdefault(file_id, kind or None)
    return list(seen.items())


def _recent_open_comments(service, file_id: str, now: datetime) -> list[dict]:
    result = service.comments().list(
        fileId=file_id, pageSize=40, includeDeleted=False,
        fields="comments(content,author(displayName),createdTime,modifiedTime,resolved,replies(content,author(displayName)))",
    ).execute()
    cutoff = now.astimezone(timezone.utc) - timedelta(days=COMMENT_WINDOW_DAYS)
    comments = []
    for c in result.get("comments", []):
        if c.get("resolved"):
            continue
        modified = datetime.fromisoformat(c.get("modifiedTime", c["createdTime"]).replace("Z", "+00:00"))
        if modified < cutoff:
            continue
        replies = c.get("replies", [])
        comments.append({
            "author": c["author"]["displayName"],
            "date": c["createdTime"][:10],
            "text": _tidy_comment(c["content"])[:MAX_COMMENT_CHARS],
            "last_reply": (f"{replies[-1]['author']['displayName']}: {_tidy_comment(replies[-1]['content'])[:MAX_COMMENT_CHARS]}"
                           if replies else None),
            "_sort": modified,
        })
    comments.sort(key=lambda c: c["_sort"], reverse=True)
    for c in comments:
        del c["_sort"]
    return comments


def fetch_drive_context(service, file_id: str, kind: str | None, now: datetime) -> dict:
    """Name, extract and open recent comments of a Drive file. Never raises:
    a file the account can't open comes back with `error` set."""
    from core.tools.drive_tools import read_drive_file

    info: dict = {"id": file_id, "kind": _KINDS.get(kind, "Archivo"), "url": None}
    try:
        meta = service.files().get(fileId=file_id, fields="name,mimeType,modifiedTime,webViewLink").execute()
        info.update(name=meta["name"].strip(), modified=meta.get("modifiedTime", "")[:10], url=meta.get("webViewLink"))
    except Exception as exc:  # noqa: BLE001 - no access / deleted / API hiccup
        logger.warning("drive file %s unavailable: %s", file_id[:8], type(exc).__name__)
        return info | {"name": "(archivo sin acceso)", "error": type(exc).__name__, "comments": []}

    try:
        content = read_drive_file(file_id).get("content", "")
        info["extract"] = clean_body(content, MAX_DOC_CHARS)
    except Exception as exc:  # noqa: BLE001 - e.g. a video or other non-exportable file
        logger.warning("drive content %s unreadable: %s", file_id[:8], type(exc).__name__)
        info["extract"] = ""
    try:
        info["comments"] = _recent_open_comments(service, file_id, now)[:MAX_COMMENTS_PER_DOC]
    except Exception as exc:  # noqa: BLE001
        logger.warning("drive comments %s unavailable: %s", file_id[:8], type(exc).__name__)
        info["comments"] = []
    return info


def build_digest(emails: list[dict], now: datetime) -> dict | None:
    """emails: Gmail search hits (id/subject/from/...). Returns
    {"emails": [... with full cleaned text and the titles of linked docs],
     "docs": [... each linked file once, with extract and open comments]}
    or None when Google isn't usable."""
    from core.tools.gmail_tools import read_email

    credentials = get_credentials()
    if credentials is None:
        return None
    drive = build("drive", "v3", credentials=credentials)

    enriched, doc_refs = [], {}
    for hit in emails:
        try:
            full = read_email(hit["id"])
            body = full.get("body", "")
        except Exception as exc:  # noqa: BLE001 - fall back to the snippet for this mail
            logger.warning("read_email failed (%s), using snippet", type(exc).__name__)
            body = hit.get("snippet") or ""
        file_ids = extract_file_ids(body)
        for file_id, kind in file_ids:
            doc_refs.setdefault(file_id, kind)
        enriched.append({"from": hit.get("from"), "subject": hit.get("subject"),
                         "message": clean_body(body), "_file_ids": [f for f, _ in file_ids]})

    docs = [fetch_drive_context(drive, fid, kind, now) for fid, kind in list(doc_refs.items())[:MAX_DOCS]]
    names = {d["id"]: d["name"] for d in docs}
    for item in enriched:
        item["documents"] = [names[f] for f in item.pop("_file_ids") if f in names]
    return {"emails": enriched, "docs": docs}
