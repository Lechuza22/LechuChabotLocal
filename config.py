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
