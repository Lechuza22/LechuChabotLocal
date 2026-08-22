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
from core.tools import datetime_tools as _datetime_tools  # noqa: E402,F401
from core.tools import weather as _weather  # noqa: E402,F401
from core.tools import maps as _maps  # noqa: E402,F401
from core.tools import gmail_tools as _gmail_tools  # noqa: E402,F401
from core.tools import drive_tools as _drive_tools  # noqa: E402,F401
from core.tools import calendar_tools as _calendar_tools  # noqa: E402,F401
from core.tools import wikipedia_tools as _wikipedia_tools  # noqa: E402,F401
from core.tools import websearch_tools as _websearch_tools  # noqa: E402,F401
from core.tools import web_tools as _web_tools  # noqa: E402,F401
from core.tools import git_tools as _git_tools  # noqa: E402,F401
