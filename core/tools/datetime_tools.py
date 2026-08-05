from __future__ import annotations

from datetime import datetime

from core.tools import Tool, register


def get_current_time() -> dict:
    now = datetime.now().astimezone()
    return {
        "iso": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": now.strftime("%A"),
        "timezone": str(now.tzinfo),
    }


register(Tool(
    name="get_current_time",
    description="Get the current date and time from the local machine's system clock.",
    parameters={"type": "object", "properties": {}, "required": []},
    func=get_current_time,
))
