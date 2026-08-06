from __future__ import annotations

import json
from typing import AsyncIterator, NamedTuple, Union

from nicegui import run

from core.agents import Agent
from core.llm import OllamaClient
from core.tools import TOOL_REGISTRY


class FinalAnswer(NamedTuple):
    content: str


class PendingConfirmation(NamedTuple):
    tool_call_id: str
    tool_name: str
    args: dict


class Continue(NamedTuple):
    pass


StepResult = Union[FinalAnswer, PendingConfirmation, Continue]


def _append_tool_result(messages: list[dict], tool_call_id: str, result: dict) -> None:
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(result),
    })


def execute_tool(tool_name: str, args: dict) -> dict:
    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        return {"error": f"Unknown tool '{tool_name}'"}
    try:
        return tool.func(**args)
    except Exception as e:  # tool errors are surfaced to the model, not raised
        return {"error": str(e)}


async def step_agent_stream(client: OllamaClient, agent: Agent, messages: list[dict]) -> tuple[AsyncIterator[str], dict]:
    """Streams one model turn's reply.

    Returns (chunks, box). `chunks` yields text pieces as they arrive - drive
    it to completion (e.g. via _stream_into_chat) before reading box["result"],
    which is only populated once the generator is exhausted. Tool-call chunks
    carry no content, so turns that end up calling a tool just yield nothing.
    """
    box: dict = {"result": None}

    async def _gen() -> AsyncIterator[str]:
        full_content = ""
        tool_calls = None
        async for chunk in client.chat_stream(
            model=agent.model, messages=messages, tools=[t.schema for t in agent.tools]
        ):
            msg = chunk.get("message", {})
            piece = msg.get("content", "")
            if piece:
                full_content += piece
                yield piece
            if msg.get("tool_calls"):
                tool_calls = msg["tool_calls"]

        assistant_msg: dict = {"role": "assistant", "content": full_content}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        if not tool_calls:
            box["result"] = FinalAnswer(full_content)
            return

        for call in tool_calls:
            name = call["function"]["name"]
            args = call["function"]["arguments"]
            if isinstance(args, str):
                args = json.loads(args) if args else {}
            call_id = call.get("id", name)
            tool = TOOL_REGISTRY.get(name)

            if tool is None:
                _append_tool_result(messages, call_id, {"error": f"Unknown tool '{name}'"})
            elif tool.requires_confirmation:
                box["result"] = PendingConfirmation(call_id, name, args)
                return
            else:
                result = await run.io_bound(execute_tool, name, args)
                _append_tool_result(messages, call_id, result if result is not None else {"error": "cancelled"})

        box["result"] = Continue()

    return _gen(), box
