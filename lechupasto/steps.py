"""Catalog of pipeline steps a task can use. Steps fetch data in plain code;
only `llm_summarize` touches the local model (see the reliability findings in
project memory: code gathers, the model writes)."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from core import briefing


def calendar_events(now: datetime, params: dict, ctx: dict):
    return briefing.fetch_events(now)  # list | None when Google is unavailable


def emails(now: datetime, params: dict, ctx: dict):
    return briefing.fetch_emails(now)  # list | None


def llm_summarize(now: datetime, params: dict, ctx: dict):
    source = ctx.get(params["input"])
    if source is None:
        return None
    if not source:
        return ""
    return briefing.summarize_emails(source)


STEP_CATALOG: dict[str, Callable] = {
    "calendar_events": calendar_events,
    "emails": emails,
    "llm_summarize": llm_summarize,
}
