from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from core.tools import TOOL_REGISTRY, Tool

logger = logging.getLogger(__name__)


@dataclass
class Agent:
    id: str
    name: str
    model: str
    system_prompt: str
    tool_names: list[str] = field(default_factory=list)

    @property
    def tools(self) -> list[Tool]:
        return [TOOL_REGISTRY[n] for n in self.tool_names if n in TOOL_REGISTRY]


def load_agents(agents_dir: Path) -> dict[str, Agent]:
    registry: dict[str, Agent] = {}
    for path in sorted(agents_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        tool_names = data.get("tools", [])
        unknown = [t for t in tool_names if t not in TOOL_REGISTRY]
        if unknown:
            logger.warning("%s: unknown tools %s, skipping them", path.name, unknown)
            tool_names = [t for t in tool_names if t in TOOL_REGISTRY]
        registry[data["id"]] = Agent(
            id=data["id"],
            name=data["name"],
            model=data["model"],
            system_prompt=data["system_prompt"],
            tool_names=tool_names,
        )
    return registry
