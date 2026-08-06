from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from config import CONFIG
from core.tools import Tool, register

MAX_FILE_SIZE = CONFIG.filesystem.max_file_size_bytes

# The whitelist defaults to the global sandbox folder(s) from config.yaml, but
# a folder-backed project (opened via "Abrir carpeta...") replaces it for the
# duration of that project being active - see set_active_roots().
_active_roots: list[Path] = list(CONFIG.filesystem.whitelisted_folders)


def set_active_roots(folder_path: str | None) -> None:
    global _active_roots
    if folder_path:
        _active_roots = [Path(folder_path).expanduser().resolve(strict=False)]
    else:
        _active_roots = list(CONFIG.filesystem.whitelisted_folders)


def get_active_roots() -> list[Path]:
    return list(_active_roots)


def _resolve_and_validate(path: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise ValueError(f"Path must be absolute, got '{path}'")
    resolved = candidate.resolve(strict=False)
    for root in _active_roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise PermissionError(
        f"'{path}' is outside the whitelisted folders: {[str(r) for r in _active_roots]}"
    )


def list_dir(path: str) -> dict:
    target = _resolve_and_validate(path)
    if not target.exists():
        raise FileNotFoundError(f"'{path}' does not exist")
    if not target.is_dir():
        raise NotADirectoryError(f"'{path}' is not a directory")
    entries = []
    for child in sorted(target.iterdir()):
        entries.append({
            "name": child.name,
            "type": "dir" if child.is_dir() else "file",
            "size": child.stat().st_size if child.is_file() else None,
        })
    return {"path": str(target), "entries": entries}


def _extract_pdf_text(target: Path) -> str:
    reader = PdfReader(str(target))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(p for p in pages if p.strip())
    if not text.strip():
        return (
            "[No se pudo extraer texto de este PDF - probablemente es un documento "
            "escaneado (imagen) sin capa de texto.]"
        )
    return text


def read_file(path: str) -> dict:
    target = _resolve_and_validate(path)
    if not target.exists():
        raise FileNotFoundError(f"'{path}' does not exist")
    if not target.is_file():
        raise IsADirectoryError(f"'{path}' is not a file")
    if target.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(f"'{path}' exceeds the max readable size ({MAX_FILE_SIZE} bytes)")
    if target.suffix.lower() == ".pdf":
        return {"path": str(target), "content": _extract_pdf_text(target)}
    return {"path": str(target), "content": target.read_text(errors="replace")}


def read_file_bytes(path: str) -> bytes:
    """Same whitelist/size guard as read_file, but for binary content (images, PDFs)
    that the UI's document preview needs raw - not a registered LLM tool."""
    target = _resolve_and_validate(path)
    if not target.exists():
        raise FileNotFoundError(f"'{path}' does not exist")
    if not target.is_file():
        raise IsADirectoryError(f"'{path}' is not a file")
    if target.stat().st_size > MAX_FILE_SIZE:
        raise ValueError(f"'{path}' exceeds the max readable size ({MAX_FILE_SIZE} bytes)")
    return target.read_bytes()


def write_file(path: str, content: str) -> dict:
    target = _resolve_and_validate(path)
    if len(content.encode()) > MAX_FILE_SIZE:
        raise ValueError(f"Content exceeds the max writable size ({MAX_FILE_SIZE} bytes)")
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(content)
    return {"path": str(target), "overwritten": existed, "bytes_written": len(content.encode())}


def delete_file(path: str) -> dict:
    target = _resolve_and_validate(path)
    if not target.exists():
        raise FileNotFoundError(f"'{path}' does not exist")
    if target.is_dir():
        raise IsADirectoryError(f"'{path}' is a directory, refusing to delete")
    target.unlink()
    return {"path": str(target), "deleted": True}


register(Tool(
    name="list_dir",
    description="List files and subdirectories inside a whitelisted folder.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Absolute path to a whitelisted directory"}},
        "required": ["path"],
    },
    func=list_dir,
))

register(Tool(
    name="read_file",
    description="Read the text contents of a file inside a whitelisted folder. PDFs are text-extracted automatically.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Absolute path to a whitelisted file"}},
        "required": ["path"],
    },
    func=read_file,
))

register(Tool(
    name="write_file",
    description="Create or overwrite a text file inside a whitelisted folder. Requires user confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the target file"},
            "content": {"type": "string", "description": "Full text content to write"},
        },
        "required": ["path", "content"],
    },
    func=write_file,
    requires_confirmation=True,
))

register(Tool(
    name="delete_file",
    description="Delete a file inside a whitelisted folder. Requires user confirmation.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Absolute path to the file to delete"}},
        "required": ["path"],
    },
    func=delete_file,
    requires_confirmation=True,
))
