"""MCP streamable-http клиент батареи (перенос .scratch/mcp-weak-model/harness.py).

Что: синхронный JSON-RPC клиент поверх httpx — initialize/tools/list/tools/call,
парсинг SSE (событие может резать JSON на несколько data:-строк).
Когда: раннер батареи `pdm mcp-eval` и ручные прогоны против mcp-pdm/defmcp.
Возвращает: McpEndpoint.list_tools() — сырые MCP-описания инструментов;
call_tool() — ToolCallResult (ok/is_error/error_text/размер/мс).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def parse_body(text: str) -> Dict[str, Any]:
    """Тело ответа streamable-http: SSE ('event: message\\ndata: {...}') или JSON.

    SSE-событие может резать JSON на несколько data:-строк — склеиваем их
    внутри события (разделитель \\n по спецификации SSE). Из нескольких
    событий берём первое, распарсившееся в валидный JSON.
    """
    if "data: " in text or text.startswith("data:"):
        events: List[str] = []
        current: List[str] = []
        for raw_line in text.splitlines():
            line = raw_line.rstrip("\r")
            if not line.strip():
                if current:
                    events.append("\n".join(current))
                    current = []
                continue
            if line.startswith("data:"):
                current.append(line[len("data:"):].lstrip(" "))
        if current:
            events.append("\n".join(current))
        for payload in events:
            try:
                return json.loads(payload)
            except ValueError:
                continue
        raise ValueError(f"SSE без валидного JSON: {text[:200]!r}")
    return json.loads(text)


def tool_result_to_obj(res: Any) -> Any:
    """result тулза → python-объект: structuredContent | text(JSON) | text."""
    if not isinstance(res, dict):
        return res
    sc = res.get("structuredContent")
    if sc is not None:
        return sc
    content = res.get("content") or []
    for part in content:
        if part.get("type") == "text":
            try:
                return json.loads(part["text"])
            except (ValueError, TypeError):
                return part["text"]
    return res


def _default_transport(url: str, payload: Dict[str, Any], headers: Dict[str, str],
                       timeout: float) -> Tuple[int, str, Dict[str, str]]:
    """httpx-пост: возвращает (status, body-текст, заголовки).

    Отдельная функция (инжектится в тестах) — чтобы парсинг/сессия
    гонялись без сети. bytes декодируем сами: без charset в content-type
    httpx/requests декодируют text/* как latin-1 и ломают кириллицу.
    """
    response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    return response.status_code, response.content.decode("utf-8", "replace"), \
        dict(response.headers)


Transport = Callable[[str, Dict[str, Any], Dict[str, str], float],
                     Tuple[int, str, Dict[str, str]]]


@dataclass
class ToolCallResult:
    """Один tools/call: что послали, что вернулось, сколько это стоило."""

    tool: str
    arguments: Dict[str, Any]
    ok: Any = None                 # распарсенный результат (или text)
    is_error: bool = False         # isError=true либо RPC/транспорт-ошибка
    error_text: str = ""
    chars: int = 0                 # размер результата, символов
    ms: int = 0
    notes: List[str] = field(default_factory=list)


class McpEndpoint:
    """Один MCP-сервер батареи (read=mcp-pdm:8015, write=defmcp:8016)."""

    def __init__(self, name: str, url: str,
                 transport: Optional[Transport] = None,
                 timeout: float = 180.0):
        self.name = name
        self.url = url
        self._transport = transport or _default_transport
        self._timeout = timeout
        self._session: Optional[str] = None
        self._request_id = 0

    # -- низкий уровень ----------------------------------------------------

    def _rpc(self, method: str, params: Optional[Dict[str, Any]],
             notification: bool = False) -> Tuple[Optional[Dict[str, Any]],
                                                  Dict[str, str]]:
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notification:
            self._request_id += 1
            payload["id"] = self._request_id
        if params is not None:
            payload["params"] = params
        headers = dict(_HEADERS)
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        status, text, resp_headers = self._transport(
            self.url, payload, headers, self._timeout)
        if notification:
            return None, resp_headers
        if status >= 400:
            raise RuntimeError(f"HTTP {status}: {text[:200]}")
        message = parse_body(text)
        if not self._session:
            # httpx отдаёт имена заголовков в нижнем регистре, дикты
            # фейков — как записаны; сессию ищем без учёта регистра.
            for key, value in (resp_headers or {}).items():
                if key.lower() == "mcp-session-id" and value:
                    self._session = value
                    break
        return message, resp_headers

    # -- публичное ----------------------------------------------------------

    def _rpc_resession(self, method: str, params: Optional[Dict[str, Any]]):
        """rpc с одним ре-хендшейком, если сервер потерял сессию (TTL):
        прод-прогон 07.10 — к поздним кейсам mcp-pdm отвечал 404
        'Session not found' и кейс умирал целиком на tools/list."""
        try:
            return self._rpc(method, params)
        except RuntimeError as exc:
            text = str(exc).lower()
            session_lost = "session not found" in text or "http 404" in text
            if not (self._session and session_lost):
                raise
            self._session = None
            self.connect()
            return self._rpc(method, params)

    def connect(self) -> str:
        """Полный handshake; stateless-серверу сессия не нужна, но вежливость
        бесплатна (перенос harness.py)."""
        message, _ = self._rpc("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "pdm-mcp-eval", "version": "1.0"},
        })
        if message and "error" in message:
            raise RuntimeError(f"initialize failed: {message['error']}")
        self._rpc("notifications/initialized", {}, notification=True)
        return self._session or ""

    def list_tools(self) -> List[Dict[str, Any]]:
        if not self._session:
            self.connect()
        message, _ = self._rpc_resession("tools/list", {})
        if message is None or "error" in message:
            error = (message or {}).get("error", {}).get("message", "?")
            raise RuntimeError(f"tools/list error: {error}")
        return message["result"]["tools"]

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> ToolCallResult:
        if not self._session:
            self.connect()
        started = time.time()
        try:
            message, _ = self._rpc_resession(
                "tools/call", {"name": name, "arguments": arguments})
        except Exception as exc:  # noqa: BLE001 — транспорт-ошибка = результат
            return ToolCallResult(tool=name, arguments=arguments,
                                  is_error=True, error_text=f"транспорт: {exc}",
                                  ms=int((time.time() - started) * 1000))
        elapsed = int((time.time() - started) * 1000)
        if message and "error" in message:
            text = message["error"].get("message", "")
            return ToolCallResult(tool=name, arguments=arguments,
                                  is_error=True, error_text=text,
                                  chars=len(text), ms=elapsed)
        result = (message or {}).get("result", {})
        is_error = bool(result.get("isError"))
        obj = tool_result_to_obj(result)
        text = obj if isinstance(obj, str) else json.dumps(
            obj, ensure_ascii=False, default=str)
        return ToolCallResult(
            tool=name, arguments=arguments, ok=None if is_error else obj,
            is_error=is_error,
            error_text=text if is_error else "",
            chars=len(text), ms=elapsed)
