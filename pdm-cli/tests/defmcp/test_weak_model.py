"""Мягкий коэрсинг аргументов defmcp под слабые модели (weak_model.py).

Слой: pydantic-ошибка валидации → однозначный ремонт («да»→true, 123→"123")
→ один повтор; неоднозначное — русская ошибка с подсказкой по каждому полю.
"""

import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from pdm_cli.defmcp.context import BpContext
from pdm_cli.defmcp.server import make_server
from pdm_cli.defmcp.weak_model import repair_arguments


@pytest.fixture()
def ctx(tmp_path):
    ws = tmp_path / "ws"
    bp = ws / "testbp"
    (bp / "tasks").mkdir(parents=True)
    (bp / "process.yaml").write_text("slug: testbp\n", encoding="utf-8")
    return BpContext(repo_root=tmp_path, drafts_root=ws)


def _server(ctx):
    return make_server(ctx)


def _call(server, name, arguments):
    """Разворачиваем результат FastMCP: (content, structured) | dict |
    список контент-блоков с JSON-текстом."""
    import json

    result = asyncio.run(server.call_tool(name, arguments))
    if isinstance(result, tuple) and len(result) > 1 and isinstance(result[1], dict):
        inner = result[1]
        return inner.get("result", inner) if set(inner) == {"result"} else inner
    if isinstance(result, dict):
        return result
    parts = list(result)
    if parts and isinstance(parts[0], dict):
        return parts[0]
    texts = [getattr(p, "text", "") for p in parts]
    return json.loads("".join(t for t in texts if t))


# ---------- чистая логика ремонта ----------

def test_repair_bool_from_russian_word():
    schema = {"properties": {"confirm_push": {"type": "boolean"}}}
    assert repair_arguments(schema, {"confirm_push": "да"}) == {
        "confirm_push": True}


def test_repair_string_from_int():
    schema = {"properties": {"path": {"type": "string"}}}
    assert repair_arguments(schema, {"path": 123}) == {"path": "123"}


def test_repair_array_from_csv():
    schema = {"properties": {"paths": {"type": "array"}}}
    assert repair_arguments(schema, {"paths": "a.yaml, b.yaml"}) == {
        "paths": ["a.yaml", "b.yaml"]}


def test_no_repair_for_ambiguous_values():
    schema = {"properties": {"slug": {"type": "string"}}}
    # словарь вместо строки не чинится молча
    assert repair_arguments(schema, {"slug": {"a": 1}}) is None


def test_no_repair_when_nothing_to_fix():
    schema = {"properties": {"slug": {"type": "string"}}}
    assert repair_arguments(schema, {"slug": "ok"}) is None


# ---------- сквозной путь через сервер ----------

def test_read_file_with_int_path_is_repaired(ctx):
    """Слабая модель шлёт path числом — чиним в строку и доходим до
    бизнес-проверки (файла '123' нет), а не до pydantic-отказа."""
    server = _server(ctx)
    result = _call(server, "bp_read_file", {"path": 123})
    assert result["status"] == "error"
    assert "123" in result["error"]


def test_read_file_without_path_is_russian_error(ctx):
    """Отсутствующий required-параметр — русская подсказка, не pydantic-шум."""
    server = _server(ctx)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool("bp_read_file", {}))
    message = str(excinfo.value)
    assert "Неверные аргументы" in message
    assert "path" in message


def test_draft_save_with_int_slug_is_repaired(ctx):
    """Слабая модель шлёт slug числом — чинится в строку и доходит до
    бизнес-проверки (compile-гейт эхирует слаг), а не рвёт цикл
    pydantic-отказом (идиома test_script_check_int_path…)."""
    from pdm_cli.api_client import PdmApiClient

    ctx.api = PdmApiClient(base_url="http://pdm.local", api_key="t")
    server = _server(ctx)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool(
            "bp_draft_save", {"slug": 424242}))
    message = str(excinfo.value)
    assert "424242" in message  # число починилось в строку, слаг дошёл
    # дошли до доменной проверки (compile-гейт), а не до валидации аргументов
    assert "process.yaml" in message or "workspace" in message


def test_string_slug_digit_is_repaired(ctx):
    """bp_compile(slug=123) — число чинится в строку, цикл не рвётся."""
    server = _server(ctx)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool("bp_compile", {"slug": {"некорректно": 1}}))
    # неоднозначное значение → русская подсказка, не английская простыня
    assert "Неверные аргументы" in str(excinfo.value)
