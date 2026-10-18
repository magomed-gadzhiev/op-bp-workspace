"""OpenAI-compatible LLM-клиент батареи (перенос agent_loop.py).

Что: POST {base}/chat/completions с tools= (function calling), без стрима.
Когда: раннер `pdm mcp-eval` против любого openai-compatible эндпоинта
(llama-server :11434/v1, ollama, прокси для смоука).
Возвращает: LlmResponse — finish_reason, content, tool_calls[], usage, мс.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

import httpx


@dataclass
class LlmToolCall:
    """Один tool_call модели (arguments — сырая JSON-строка, как прислала)."""

    id: str
    name: str
    arguments_raw: str


@dataclass
class LlmResponse:
    finish_reason: str | None
    content: str
    tool_calls: List[LlmToolCall] = field(default_factory=list)
    usage: Dict[str, Any] = field(default_factory=dict)
    ms: int = 0


Poster = Callable[[Dict[str, Any]], Dict[str, Any]]


def _default_poster(base_url: str, model: str, timeout: float) -> Poster:
    url = f"{base_url.rstrip('/')}/chat/completions"

    def post(payload: Dict[str, Any]) -> Dict[str, Any]:
        # Один ретрай на таймаут/транспорт/5xx: llama-server с 2 слотами может
        # ставить запрос в очередь — единичный флук не должен валить кейс
        # (прод-прогон 07.10: push-refusal умер на LLM timeout в шаге 5).
        last_error: Exception | None = None
        for attempt in (1, 2):
            try:
                response = httpx.post(url, json={**payload, "model": model},
                                      timeout=timeout)
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError,
                    httpx.HTTPStatusError) as exc:
                if (isinstance(exc, httpx.HTTPStatusError)
                        and exc.response.status_code < 500):
                    raise  # клиентская ошибка (4xx) — ретраем не лечится
                last_error = exc
                if attempt == 1:
                    time.sleep(5)
        raise last_error  # type: ignore[misc]

    return post


class LlmClient:
    """Минимальный chat-клиент: ровно то, что нужно агентному циклу."""

    def __init__(self, base_url: str, model: str, timeout: float = 300.0,
                 temperature: float = 0.1, poster: Poster | None = None):
        # 0.1, а не 0: на Qwen-MoE жадное декодирование (temp=0) усиливает
        # повторы одних и тех же tool_calls — прод-прогоны 07.10 при temp=0
        # ушли в циклы (bp_list_files ×6 подряд). Подбор — флагом
        # --llm-temperature; детект циклов — в runner (fail_reason "loop").
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self._poster = poster or _default_poster(base_url, model, timeout)

    def chat(self, messages: List[Dict[str, Any]],
             tools: List[Dict[str, Any]]) -> LlmResponse:
        started = time.time()
        data = self._poster({
            "messages": messages,
            "tools": tools,
            "temperature": self.temperature,
            "stream": False,
        })
        choice = data["choices"][0]
        message = choice.get("message") or {}
        tool_calls = [
            LlmToolCall(
                id=tc.get("id", f"call-{i}"),
                name=(tc.get("function") or {}).get("name", ""),
                arguments_raw=(tc.get("function") or {}).get("arguments") or "{}",
            )
            for i, tc in enumerate(message.get("tool_calls") or [])
        ]
        return LlmResponse(
            finish_reason=choice.get("finish_reason"),
            content=(message.get("content") or "").strip(),
            tool_calls=tool_calls,
            usage=data.get("usage") or {},
            ms=int((time.time() - started) * 1000),
        )
