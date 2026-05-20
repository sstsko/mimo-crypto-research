"""LLM client — OpenAI-compatible chat with token accounting.

Every call logs to the database automatically. Supports MiMo, OpenAI,
DeepSeek, OpenRouter, vLLM, or any OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .db import Database


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        db: Database,
        *,
        timeout: float = 120.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.db = db
        self._owns = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        if self._owns:
            await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20), reraise=True)
    async def chat(self, messages: list[dict[str, str]], *, agent: str = "unknown",
                   temperature: float = 0.2, max_tokens: int = 2048,
                   response_format: Optional[dict] = None,
                   scan_id: Optional[int] = None) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        t0 = time.monotonic()
        resp = await self._client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        ms = int((time.monotonic() - t0) * 1000)

        usage = data.get("usage") or {}
        self.db.record_llm(
            agent=agent, model=self.model,
            prompt_tok=int(usage.get("prompt_tokens") or 0),
            comp_tok=int(usage.get("completion_tokens") or 0),
            latency_ms=ms, scan_id=scan_id,
        )

        return data["choices"][0]["message"].get("content") or ""

    async def chat_json(self, messages: list[dict[str, str]], **kwargs) -> dict[str, Any]:
        """Chat expecting JSON. Falls back to text extraction if provider ignores response_format."""
        try:
            raw = await self.chat(messages, response_format={"type": "json_object"}, **kwargs)
        except httpx.HTTPStatusError:
            raw = await self.chat(messages, **kwargs)

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(raw[start:end + 1])
                except json.JSONDecodeError:
                    pass
            return {"_raw": raw}
