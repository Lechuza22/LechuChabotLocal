"""Builds the HTML report for a task run: phone-width (480px) so the same file
reads well in the app's iframe, a browser, and as a Telegram screenshot."""

from __future__ import annotations

import html
import re
from pathlib import Path

from lechupasto.render import HEIGHT_PROBE

MARK_SVG = (Path(__file__).parent / "assets" / "lechupasto_mark.svg").read_text(encoding="utf-8")

MAILS_SHOWN = 12

_CSS = """
:root { --brown:#a5693a; --brown-dark:#774c2a; --cream:#faf4ec; --ink:#34363c; --muted:#7a7068; --line:#eadfce; }
* { box-sizing:border-box; }
body { margin:0; background:var(--cream); color:var(--ink); width:480px;
  font:15px/1.45 -apple-system, "Helvetica Neue", Arial, sans-serif; }
header { background:var(--brown); color:#fff; padding:18px 20px; display:flex; align-items:center; gap:14px; }
header svg { width:46px; height:46px; flex:none; background:#fff; border-radius:12px; padding:3px; }
header h1 { margin:0; font-size:19px; line-height:1.2; }
header p { margin:2px 0 0; font-size:12.5px; opacity:.85; }
main { padding:6px 20px 18px; }
section { padding:14px 0 4px; border-bottom:1px solid var(--line); }
section:last-child { border-bottom:none; }
h2 { margin:0 0 8px; font-size:12px; letter-spacing:.09em; text-transform:uppercase; color:var(--brown-dark); }
ul { margin:0; padding:0; list-style:none; }
li { padding:7px 0; border-top:1px solid var(--line); }
li:first-child { border-top:none; }
.time { display:inline-block; min-width:78px; font-weight:700; color:var(--brown-dark); }
.badge { display:inline-block; background:#fff3d6; color:#8a5a00; font-size:11.5px; padding:1px 8px; border-radius:10px; margin-left:4px; white-space:nowrap; }
.quote { margin:4px 0 0 10px; padding-left:8px; border-left:3px solid var(--line); font-size:13px; color:var(--muted); }
a { color:var(--brown-dark); text-decoration:none; }
.notes { margin:8px 0 10px; color:var(--muted); font-size:13.5px; }
.empty { color:var(--muted); font-style:italic; margin:4px 0 10px; }
.warn { background:#fff3d6; border-left:4px solid #e8a33d; padding:8px 10px; border-radius:4px; margin:4px 0 10px; }
footer { padding:10px 20px 16px; font-size:11.5px; color:var(--muted); }
"""


_BULLET = re.compile(r"^[-*•]\s+")


def _inline(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(text))


def markdown_to_html(text: str) -> str:
    """Tiny converter for what the local model emits: bullets and **bold**."""
    items, paras = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _BULLET.match(line):
            items.append("<li>" + _inline(_BULLET.sub("", line)) + "</li>")
        else:
            paras.append(f"<p>{_inline(line)}</p>")
    return "".join(paras) + (f"<ul>{''.join(items)}</ul>" if items else "")


def render_section(section: dict) -> str:
    kind, title = section["kind"], html.escape(section["title"])
    if kind == "events":
        body = section["data"]
        if body is None:
            inner = '<div class="warn">No pude leer el calendario. Reconectá Google en Lechu.</div>'
        elif not body:
            inner = '<p class="empty">Sin eventos hoy.</p>'
        else:
            rows = []
            for event in body:
                start = event.get("start") or ""
                when = start[11:16] if "T" in start else "Todo el día"
                place = f" <span style='color:var(--muted)'>· {html.escape(event['location'])}</span>" if event.get("location") else ""
                rows.append(f"<li><span class='time'>{when}</span>{html.escape(event.get('title') or '(sin título)')}{place}</li>")
            inner = f"<ul>{''.join(rows)}</ul>"
    elif kind == "today":
        data = section["data"] or {}
        parts = []
        if data.get("reminders"):
            rows = "".join(
                f"<li><span class='time'>{html.escape(r['due_at'][11:16])}</span>{html.escape(r['message'])}</li>"
                for r in data["reminders"]
            )
            parts.append(f"<ul>{rows}</ul>")
        notes = data.get("notes") or []
        if notes:
            shown = ", ".join(f"<strong>{html.escape(n['title'])}</strong>" for n in notes[:6])
            more = f" y {len(notes) - 6} más" if len(notes) > 6 else ""
            parts.append(f"<p class='notes'>Notas guardadas ({len(notes)}): {shown}{more}</p>")
        inner = "".join(parts)
    elif kind == "mails":
        items = section["data"] or []
        shown = items[:MAILS_SHOWN]
        rows = "".join(
            f"<li><span class='time'>{html.escape(m['date'])}</span><strong>{html.escape(m['from'])}</strong>"
            f"<div class='quote' style='border:none;margin:0 0 0 78px;padding:0'>{html.escape(m['subject'][:90])}</div></li>"
            for m in shown
        )
        extra = f"<p class='empty'>y {len(items) - MAILS_SHOWN} más sin leer…</p>" if len(items) > MAILS_SHOWN else ""
        inner = f"<ul>{rows}</ul>{extra}"
    elif kind == "docs":
        rows = []
        for doc in section["data"] or []:
            n = len(doc["comments"])
            name = html.escape(doc["name"])
            link = f"<a href='{html.escape(doc['url'])}'>{name}</a>" if doc.get("url") else name
            quotes = "".join(
                f"<div class='quote'><b>{html.escape(c['author'])}:</b> {html.escape(c['text'][:140])}{'…' if len(c['text']) > 140 else ''}</div>"
                for c in doc["comments"][:3]
            )
            more = f"<div class='quote'>y {n - 3} más…</div>" if n > 3 else ""
            rows.append(f"<li><strong>{link}</strong> <span class='badge'>{n} comentario{'s' if n != 1 else ''} abierto{'s' if n != 1 else ''}</span>{quotes}{more}</li>")
        inner = f"<ul>{''.join(rows)}</ul>"
    else:  # text
        data = section["data"]
        if data is None:
            inner = '<div class="warn">No pude leer los mails. Reconectá Google en Lechu.</div>'
        elif not data:
            inner = '<p class="empty">Sin mails nuevos.</p>'
        else:
            inner = markdown_to_html(data)
    return f"<section><h2>{title}</h2>{inner}</section>"


def build_report_html(title: str, subtitle: str, sections: list[dict], footer: str) -> str:
    body = "".join(render_section(s) for s in sections)
    return (
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=480'><title>{html.escape(title)}</title><style>{_CSS}</style></head><body>"
        f"<header>{MARK_SVG.split('?>', 1)[-1]}<div><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div></header>"
        f"<main>{body}</main><footer>{html.escape(footer)}</footer>{HEIGHT_PROBE}</body></html>"
    )
