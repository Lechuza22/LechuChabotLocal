from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[..., dict]
    requires_confirmation: bool = False

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


TOOL_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    TOOL_REGISTRY[tool.name] = tool
    return tool


# Import submodules for their registration side-effects. Placed at the
# bottom so `Tool`/`register` already exist when those modules import them.
from core.tools import filesystem as _filesystem  # noqa: E402,F401
from core.tools import memory_tools as _memory_tools  # noqa: E402,F401
