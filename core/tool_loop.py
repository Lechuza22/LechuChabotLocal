from __future__ import annotations

import json
from typing import NamedTuple, Union

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


def step_agent(client: OllamaClient, agent: Agent, messages: list[dict]) -> StepResult:
    assistant_msg = client.chat(
        model=agent.model,
        messages=messages,
        tools=[t.schema for t in agent.tools],
    )
    messages.append(assistant_msg)

    tool_calls = assistant_msg.get("tool_calls")
    if not tool_calls:
        return FinalAnswer(assistant_msg.get("content", ""))

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
            return PendingConfirmation(call_id, name, args)
        else:
            _append_tool_result(messages, call_id, execute_tool(name, args))

    return Continue()


def drive_turn(client: OllamaClient, agent: Agent, messages: list[dict], max_iterations: int) -> tuple[str | None, PendingConfirmation | None]:
    """Runs step_agent repeatedly. Returns (final_text, pending) - exactly one is non-None,
    unless the iteration cap is hit, in which case final_text carries a fallback message."""
    for _ in range(max_iterations):
        result = step_agent(client, agent, messages)
        if isinstance(result, FinalAnswer):
            return result.content, None
        if isinstance(result, PendingConfirmation):
            return None, result
        # Continue -> loop again
    fallback = "Me detuve después de demasiadas llamadas a herramientas. Probá simplificar el pedido."
    messages.append({"role": "assistant", "content": fallback})
    return fallback, None
