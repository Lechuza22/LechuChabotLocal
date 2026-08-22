from __future__ import annotations

import httpx
import trafilatura

from core.tools import Tool, register
from core.tools.filesystem import validate_path

_USER_AGENT = "Lechu/1.0 (local desktop assistant; personal use)"

MAX_DOWNLOAD_SIZE = 25_000_000  # 25MB - generous for personal files without risking disk/RAM


def fetch_url(url: str, max_chars: int = 5000) -> dict:
    """Fetches `url` and extracts its main readable text (strips nav/ads/boilerplate) -
    unlike search_web, which only returns title+snippet for several results."""
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _USER_AGENT})
            resp.raise_for_status()
    except httpx.HTTPError as e:
        return {"error": f"No se pudo acceder a la URL: {e}"}

    text = trafilatura.extract(resp.text, url=url)
    if not text:
        return {"error": "No se pudo extraer contenido legible de esa página."}

    max_chars = max(500, min(max_chars, 20_000))
    return {
        "url": url,
        "content": text[:max_chars],
        "truncated": len(text) > max_chars,
    }


def download_file(url: str, path: str) -> dict:
    """Downloads `url` into `path`, which must be inside a whitelisted folder. Streams
    to disk with a hard size cap instead of buffering the whole response in memory."""
    target = validate_path(path)
    downloaded = 0
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            with client.stream("GET", url, headers={"User-Agent": _USER_AGENT}) as resp:
                resp.raise_for_status()
                content_length = resp.headers.get("content-length")
                if content_length and int(content_length) > MAX_DOWNLOAD_SIZE:
                    return {
                        "error": f"El archivo declara {int(content_length):,} bytes, "
                                 f"supera el límite de descarga ({MAX_DOWNLOAD_SIZE:,} bytes)."
                    }
                with open(target, "wb") as f:
                    for chunk in resp.iter_bytes():
                        downloaded += len(chunk)
                        if downloaded > MAX_DOWNLOAD_SIZE:
                            f.close()
                            target.unlink(missing_ok=True)
                            return {
                                "error": f"El archivo supera el límite de descarga "
                                         f"({MAX_DOWNLOAD_SIZE:,} bytes), se abortó la descarga."
                            }
                        f.write(chunk)
    except httpx.HTTPError as e:
        target.unlink(missing_ok=True)
        return {"error": f"No se pudo descargar el archivo: {e}"}

    return {"path": str(target), "bytes": downloaded}


register(Tool(
    name="fetch_url",
    description=(
        "Fetch a specific web page and extract its main readable text content (title, "
        "byline, body text - navigation/ads/boilerplate stripped out). Use this to actually "
        "read a page after search_web gives you its URL - search_web alone only returns "
        "short snippets, not full content."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL to fetch, including https://"},
            "max_chars": {
                "type": "integer",
                "description": "Max characters of extracted content to return, 500-20000, defaults to 5000",
            },
        },
        "required": ["url"],
    },
    func=fetch_url,
))

register(Tool(
    name="download_file",
    description=(
        "Download a file from a URL and save it inside a whitelisted folder. Capped at "
        f"{MAX_DOWNLOAD_SIZE:,} bytes. Requires user confirmation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL of the file to download"},
            "path": {"type": "string", "description": "Absolute destination path inside a whitelisted folder"},
        },
        "required": ["url", "path"],
    },
    func=download_file,
    requires_confirmation=True,
))
