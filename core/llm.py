from __future__ import annotations

import json
from typing import Iterator

import httpx


class OllamaClient:
    def __init__(self, base_url: str, timeout: float = 120.0):
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def chat(self, model: str, messages: list[dict], tools: list[dict] | None = None) -> dict:
        payload = {"model": model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
        resp = self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json()["message"]

    def chat_stream(self, model: str, messages: list[dict], tools: list[dict] | None = None) -> Iterator[dict]:
        payload = {"model": model, "messages": messages, "stream": True}
        if tools:
            payload["tools"] = tools
        with self._client.stream("POST", "/api/chat", json=payload) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                yield json.loads(line)

    def list_models(self) -> list[str]:
        resp = self._client.get("/api/tags")
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]

    def is_reachable(self) -> bool:
        try:
            resp = self._client.get("/api/version", timeout=3.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
