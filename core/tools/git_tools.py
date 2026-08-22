from __future__ import annotations

import os
import subprocess

from core.tools import Tool, register
from core.tools.filesystem import validate_path

# GIT_TERMINAL_PROMPT=0: makes git fail fast with a clear error instead of hanging
# forever waiting for interactive username/password input that can never come here.
_GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def _run_git(args: list[str], timeout: float) -> dict:
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=timeout, env=_GIT_ENV,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"git {' '.join(args)} tardó demasiado y se canceló."}
    except FileNotFoundError:
        return {"error": "No se encontró el comando 'git' en el sistema."}

    if result.returncode != 0:
        return {"error": (result.stderr or result.stdout or "git terminó con error, sin más detalle.").strip()}
    return {"output": (result.stdout or "").strip()}


def git_clone(url: str, path: str) -> dict:
    """Clones `url` into `path`, which must be inside a whitelisted folder."""
    target = validate_path(path)
    result = _run_git(["clone", url, str(target)], timeout=120.0)
    if "error" in result:
        return result
    return {"path": str(target)}


def git_pull(path: str) -> dict:
    """Pulls the current branch's configured upstream inside the repo at `path`."""
    target = validate_path(path)
    result = _run_git(["-C", str(target), "pull"], timeout=60.0)
    if "error" in result:
        return result
    return {"path": str(target), "output": result["output"]}


def git_push(path: str) -> dict:
    """Pushes the current branch to its already-configured upstream - no remote/branch
    argument is accepted, and --force is never used, so this can't push somewhere
    unexpected or overwrite remote history."""
    target = validate_path(path)
    result = _run_git(["-C", str(target), "push"], timeout=120.0)
    if "error" in result:
        return result
    return {"path": str(target), "output": result["output"]}


register(Tool(
    name="git_clone",
    description="Clone a git repository into a whitelisted folder. Requires user confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Repository URL (https://... or git@...)"},
            "path": {"type": "string", "description": "Absolute destination path inside a whitelisted folder"},
        },
        "required": ["url", "path"],
    },
    func=git_clone,
    requires_confirmation=True,
))

register(Tool(
    name="git_pull",
    description="Pull the latest changes for the current branch's configured upstream, in a repo already cloned inside a whitelisted folder.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the repo, inside a whitelisted folder"},
        },
        "required": ["path"],
    },
    func=git_pull,
))

register(Tool(
    name="git_push",
    description=(
        "Push the current branch to its already-configured remote (no other remote/branch "
        "can be specified, and this never force-pushes). Requires user confirmation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the repo, inside a whitelisted folder"},
        },
        "required": ["path"],
    },
    func=git_push,
    requires_confirmation=True,
))
