"""MCP-клиент раннера (перенос .scratch/harness.py): streamable-http,
SSE/JSON-парсинг, сессия, инструменты/результаты."""

from pdm_cli.mcp_eval.mcp_client import (
    McpEndpoint,
    ToolCallResult,
    parse_body,
    tool_result_to_obj,
)


class FakeTransport:
    """Запоминает запросы; отвечает заготовками по method."""

    def __init__(self, responses):
        # responses: list[(status, text, headers)] либо исключение
        self.responses = list(responses)
        self.requests = []

    def __call__(self, url, payload, headers, timeout):
        self.requests.append({"url": url, "payload": payload, "headers": headers})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, text, resp_headers = item
        return status, text, resp_headers


def _rpc_ok(result, session="s-1"):
    import json as _json
    return (
        200,
        _json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}),
        {"Mcp-Session-Id": session},
    )


# ---------- парсинг тела ответа ----------

def test_parse_body_plain_json():
    assert parse_body('{"jsonrpc":"2.0","result":{"x":1}}') == {
        "jsonrpc": "2.0", "result": {"x": 1}}


def test_parse_body_sse_multiline_data():
    """SSE-событие режет JSON на несколько data:-строк — склеиваем (\\n)."""
    text = (
        "event: message\n"
        "data: {\"jsonrpc\":\"2.0\",\"result\":{\"tools\":[\n"
        "data:   {\"name\":\"bp_test\"}]}}\n"
        "\n"
    )
    msg = parse_body(text)
    assert msg["result"]["tools"][0]["name"] == "bp_test"


def test_parse_body_sse_two_events_takes_valid():
    text = (
        "event: message\n"
        "data: not-json\n"
        "\n"
        "event: message\n"
        "data: {\"jsonrpc\":\"2.0\",\"result\":{\"ok\":true}}\n"
    )
    assert parse_body(text)["result"] == {"ok": True}


def test_tool_result_to_obj_structured_content():
    assert tool_result_to_obj({"structuredContent": {"a": 1}}) == {"a": 1}


def test_tool_result_to_obj_text_json():
    res = {"content": [{"type": "text", "text": '{"b": 2}'}]}
    assert tool_result_to_obj(res) == {"b": 2}


def test_tool_result_to_obj_text_plain():
    res = {"content": [{"type": "text", "text": "# отчёт\n- шаг 1"}]}
    assert tool_result_to_obj(res) == "# отчёт\n- шаг 1"


# ---------- endpoint ----------

def test_connect_and_session_header():
    transport = FakeTransport([
        _rpc_ok({"protocolVersion": "2025-03-26"}),
        (200, "", {}),  # notifications/initialized
    ])
    ep = McpEndpoint("read", "http://x/mcp", transport=transport)
    sid = ep.connect()
    assert sid == "s-1"
    # второй запрос обязан нести заголовок сессии
    assert transport.requests[1]["headers"]["Mcp-Session-Id"] == "s-1"


def test_session_header_captured_case_insensitive():
    """httpx отдаёт имена заголовков в нижнем регистре — сессию ловим
    независимо от регистра (FastMCP без сессии отвечает 400)."""
    transport = FakeTransport([
        (200, '{"jsonrpc":"2.0","id":1,"result":{}}',
         {"mcp-session-id": "sess-42"}),
        (200, "", {}),
        _rpc_ok({"tools": []}),
    ])
    ep = McpEndpoint("write", "http://x/mcp", transport=transport)
    sid = ep.connect()
    assert sid == "sess-42"
    ep.list_tools()
    assert transport.requests[2]["headers"]["Mcp-Session-Id"] == "sess-42"


def test_list_tools_converts_names():
    transport = FakeTransport([
        _rpc_ok({"protocolVersion": "1"}),
        (200, "", {}),
        _rpc_ok({"tools": [{"name": "list_tasks", "description": "d",
                            "inputSchema": {"type": "object"}}]}),
    ])
    ep = McpEndpoint("read", "http://x/mcp", transport=transport)
    ep.connect()
    tools = ep.list_tools()
    assert [t["name"] for t in tools] == ["list_tasks"]


def test_call_tool_ok_result():
    transport = FakeTransport([
        _rpc_ok({"protocolVersion": "1"}),
        (200, "", {}),
        _rpc_ok({"content": [{"type": "text", "text": '{"items": [1,2]}'}],
                 "isError": False}),
    ])
    ep = McpEndpoint("read", "http://x/mcp", transport=transport)
    ep.connect()
    res = ep.call_tool("list_tasks", {"page_size": 5})
    assert isinstance(res, ToolCallResult)
    assert res.tool == "list_tasks"
    assert res.arguments == {"page_size": 5}
    assert res.is_error is False
    assert res.ok == {"items": [1, 2]}
    assert res.chars > 0


def test_call_tool_is_error_true():
    transport = FakeTransport([
        _rpc_ok({"protocolVersion": "1"}),
        (200, "", {}),
        _rpc_ok({"content": [{"type": "text",
                              "text": "Запуск БП #9 не найден…"}],
                 "isError": True}),
    ])
    ep = McpEndpoint("read", "http://x/mcp", transport=transport)
    ep.connect()
    res = ep.call_tool("bp_run_report", {"instance_id": 9})
    assert res.is_error is True
    assert "не найден" in res.error_text


def test_call_tool_jsonrpc_error_is_error():
    transport = FakeTransport([
        _rpc_ok({"protocolVersion": "1"}),
        (200, "", {}),
        (200, '{"jsonrpc":"2.0","id":3,"error":{"code":-32602,'
              '"message":"unknown tool"}}', {}),
    ])
    ep = McpEndpoint("read", "http://x/mcp", transport=transport)
    ep.connect()
    res = ep.call_tool("nope", {})
    assert res.is_error is True
    assert "unknown tool" in res.error_text


def test_call_tool_transport_exception_is_error():
    transport = FakeTransport([
        _rpc_ok({"protocolVersion": "1"}),
        (200, "", {}),
        RuntimeError("connection refused"),
    ])
    ep = McpEndpoint("read", "http://x/mcp", transport=transport)
    ep.connect()
    res = ep.call_tool("list_tasks", {})
    assert res.is_error is True
    assert "connection refused" in res.error_text


# ---------- ре-хендшейк по протухшей сессии ----------

def test_list_tools_reinit_on_lost_session():
    """Сервер потерял сессию (404 Session not found) → клиент делает
    handshake заново и повторяет запрос (прод-прогон 07.10, кейс 07)."""
    import json as _json
    not_found = (
        404,
        _json.dumps({"jsonrpc": "2.0", "id": 1,
                     "error": {"code": -32600,
                               "message": "Session not found"}}),
        {},
    )
    ok = (200, "", {})
    transport = FakeTransport([
        _rpc_ok({}),                                   # initialize (s-1)
        ok,                                            # initialized
        not_found,                                     # tools/list — сессия протухла
        _rpc_ok({}, session="s-2"),                    # повторный initialize
        ok,                                            # initialized
        _rpc_ok({"tools": [{"name": "bp_test"}]}),     # tools/list ок
    ])
    ep = McpEndpoint("read", "http://x/mcp", transport=transport)
    ep.connect()
    tools = ep.list_tools()
    assert [t["name"] for t in tools] == ["bp_test"]
    # повторный tools/list ушёл уже с новой сессией
    assert transport.requests[-1]["headers"]["Mcp-Session-Id"] == "s-2"
