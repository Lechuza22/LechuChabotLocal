from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass
class FilesystemConfig:
    whitelisted_folders: list[Path]
    max_file_size_bytes: int


@dataclass
class Config:
    ollama_base_url: str
    default_agent: str
    max_tool_iterations: int
    filesystem: FilesystemConfig


def _load_config(path: Path = CONFIG_PATH) -> Config:
    raw = yaml.safe_load(path.read_text())
    fs_raw = raw["filesystem"]
    whitelisted = [Path(p).expanduser().resolve(strict=False) for p in fs_raw["whitelisted_folders"]]
    for folder in whitelisted:
        folder.mkdir(parents=True, exist_ok=True)
    return Config(
        ollama_base_url=raw["ollama_base_url"],
        default_agent=raw["default_agent"],
        max_tool_iterations=int(raw["max_tool_iterations"]),
        filesystem=FilesystemConfig(
            whitelisted_folders=whitelisted,
            max_file_size_bytes=int(fs_raw["max_file_size_bytes"]),
        ),
    )


CONFIG = _load_config()
AGENTS_DIR = PROJECT_ROOT / "agents"
SKILLS_DIR = PROJECT_ROOT / "skills"
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "memory.db"


def _persist_whitelist() -> None:
    raw = yaml.safe_load(CONFIG_PATH.read_text())
    raw["filesystem"]["whitelisted_folders"] = [str(p) for p in CONFIG.filesystem.whitelisted_folders]
    CONFIG_PATH.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))


def add_whitelisted_folder(path: str) -> None:
    folder = Path(path).expanduser().resolve(strict=False)
    folder.mkdir(parents=True, exist_ok=True)
    if folder not in CONFIG.filesystem.whitelisted_folders:
        CONFIG.filesystem.whitelisted_folders.append(folder)
        _persist_whitelist()


def remove_whitelisted_folder(path: str) -> None:
    folder = Path(path).expanduser().resolve(strict=False)
    if folder in CONFIG.filesystem.whitelisted_folders:
        CONFIG.filesystem.whitelisted_folders.remove(folder)
        _persist_whitelist()
