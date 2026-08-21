#!/usr/bin/env python3
"""Regression benchmark for Lechu's tool-calling reliability.

Runs each case in cases.py against the real production code path
(core.agents.load_agents + core.llm.OllamaClient.chat_stream, the actual
agents/*.yaml and their registered tools) and checks whether the model's
first tool call matches the expected one. Talks to Ollama directly, same
as the manual verification done throughout this project's Conexiones work
(get_weather/get_directions, Gmail/Drive/Calendar, search_web/
search_wikipedia) - just made repeatable and saved for comparison instead
of a one-off terminal script each time.

Scope: only checks tool ROUTING (did it call the right tool), not the
result content, and builds messages from agent.system_prompt alone (not
app.py's build_system_message, which adds live time/folder/skills context
irrelevant to routing) - keeps this decoupled from the UI layer.

Usage:
    python3 benchmark/run_bench.py                  # all cases, 1 run each
    python3 benchmark/run_bench.py --agent google    # only that agent's cases
    python3 benchmark/run_bench.py --runs 3          # repeat each case (model isn't deterministic)
    python3 benchmark/run_bench.py --case google_send_email
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCH_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.cases import CASES  # noqa: E402
from config import AGENTS_DIR, CONFIG  # noqa: E402
from core.agents import Agent, load_agents  # noqa: E402
from core.llm import OllamaClient  # noqa: E402

RESULTS_DIR = BENCH_DIR / "results"


async def _first_tool_call(client: OllamaClient, agent: Agent, prompt: str, think: bool | None) -> str | None:
    messages = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": prompt},
    ]
    async for chunk in client.chat_stream(
        model=agent.model, messages=messages, tools=[t.schema for t in agent.tools], think=think,
    ):
        msg = chunk.get("message", {})
        if msg.get("tool_calls"):
            return msg["tool_calls"][0]["function"]["name"]
    return None


async def run_case(client: OllamaClient, agent: Agent, case: dict, runs: int, think: bool | None) -> dict:
    outcomes = [await _first_tool_call(client, agent, case["prompt"], think) for _ in range(runs)]
    passed = sum(1 for o in outcomes if o == case["expected_tool"])
    return {
        "name": case["name"],
        "agent_id": case["agent_id"],
        "prompt": case["prompt"],
        "expected_tool": case["expected_tool"],
        "outcomes": outcomes,
        "passed": passed,
        "runs": runs,
    }


async def main_async(args: argparse.Namespace) -> int:
    agents = load_agents(AGENTS_DIR)
    client = OllamaClient(CONFIG.ollama_base_url)

    cases = CASES
    if args.agent:
        cases = [c for c in cases if c["agent_id"] == args.agent]
    if args.case:
        cases = [c for c in cases if c["name"] == args.case]
    if not cases:
        print("No hay casos que coincidan con esos filtros.")
        return 1

    results = []
    total_passed = total_runs = 0
    for case in cases:
        agent_id = case["agent_id"]
        if agent_id not in agents:
            print(f"  {case['name']}: agente '{agent_id}' no existe, salteado")
            continue
        result = await run_case(client, agents[agent_id], case, args.runs, args.think)
        results.append(result)
        total_passed += result["passed"]
        total_runs += result["runs"]
        status = "OK" if result["passed"] == result["runs"] else "FAIL"
        print(f"  [{status}] {result['name']}: {result['passed']}/{result['runs']} "
              f"(esperado={result['expected_tool']}, obtuvo={result['outcomes']})")

    print(f"\nTotal: {total_passed}/{total_runs}")

    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"{timestamp}.json"
    out_path.write_text(json.dumps({
        "timestamp": timestamp,
        "think": args.think,
        "results": results,
        "total_passed": total_passed,
        "total_runs": total_runs,
    }, indent=2, ensure_ascii=False))
    print(f"Resultados guardados en {out_path}")

    await client.aclose()
    return 0 if total_passed == total_runs else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", help="Solo correr casos de este agent_id")
    parser.add_argument("--case", help="Solo correr este caso por nombre")
    parser.add_argument("--runs", type=int, default=1, help="Repeticiones por caso (default 1)")
    parser.add_argument(
        "--think", action=argparse.BooleanOptionalAction, default=None,
        help="Pasa el parámetro 'think' de Ollama (razonamiento nativo antes de responder). Default: no lo manda.",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
