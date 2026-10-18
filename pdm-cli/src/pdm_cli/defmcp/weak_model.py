"""Мягкий коэрсинг аргументов defmcp под слабые модели (Qwen3.6-35B-A3B).

Зеркало ProfiledFastMCP из pdm/backend/mcp_server/server.py (спека 138):
пакеты развёртываются независимо, поэтому логика продублирована, а не
вынесена в общую зависимость. Слабая модель регулярно присылает «почти
правильные» аргументы (path=123 вместо строки, confirm_push="да"); pydantic
отвечает английской простынёй без подсказки, и модель зацикливается.
Слой: коэрсинг по inputSchema → один повтор → русская ошибка с подсказкой.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

_TRUTHY = {"true", "да", "yes", "1", "y", "д"}
_FALSY = {"false", "нет", "no", "0", "n", "н"}

_TYPE_HINTS = {
    "integer": "передай целое число (например 14)",
    "number": "передай число (например 2.5)",
    "boolean": "используй true или false",
    "string": "передай строку, например 'lem/process.yaml'",
    "array": "передай список, например [\"a\", \"b\"]",
}


def _expected_type(prop: dict) -> str | None:
    if "type" in prop:
        return prop["type"]
    for variant in prop.get("anyOf", []) + prop.get("oneOf", []):
        variant_type = variant.get("type")
        if variant_type and variant_type != "null":
            return variant_type
    return None


def repair_arguments(schema: dict, arguments: dict) -> dict | None:
    """Однозначные исправления типов («14»→14, «да»→true, 123→"123").

    Возвращает копию с правками или None, если чинить нечего/нечем —
    неоднозначные значения не трогаем, их объяснит explain_validation_error.
    """
    properties = schema.get("properties") or {}
    repaired = dict(arguments)
    changed = False
    for key, value in arguments.items():
        expected = _expected_type(properties.get(key) or {})
        if expected == "integer":
            if isinstance(value, str) and value.strip().lstrip("-").isdigit():
                repaired[key] = int(value.strip())
                changed = True
        elif expected == "number":
            if isinstance(value, str):
                try:
                    repaired[key] = float(value.strip())
                    changed = True
                except ValueError:
                    pass
        elif expected == "boolean":
            if isinstance(value, str):
                word = value.strip().lower()
                if word in _TRUTHY:
                    repaired[key] = True
                    changed = True
                elif word in _FALSY:
                    repaired[key] = False
                    changed = True
            elif isinstance(value, int) and not isinstance(value, bool):
                repaired[key] = bool(value)
                changed = True
        elif expected == "string":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                repaired[key] = str(value)
                changed = True
        elif expected == "array":
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.startswith("["):
                    try:
                        import json

                        repaired[key] = json.loads(stripped)
                        changed = True
                    except ValueError:
                        pass
                elif "," in stripped:
                    repaired[key] = [part.strip() for part in stripped.split(",")]
                    changed = True
    return repaired if changed else None


def explain_validation_error(name: str, schema: dict, error: Exception) -> str:
    """Русская переупаковка pydantic-ошибки с подсказкой по каждому полю."""
    lines = [f"Неверные аргументы инструмента '{name}'."]
    properties = schema.get("properties") or {}
    message = str(error)
    mentioned = [p for p in properties if p in message]
    for field in mentioned or list(properties)[:5]:
        expected = _expected_type(properties[field]) or "указан в описании инструмента"
        hint = _TYPE_HINTS.get(expected, "проверь описание инструмента")
        lines.append(f"Параметр '{field}': ожидается {expected}. {hint}.")
    if not mentioned:
        lines.append("Проверь имена и типы параметров по описанию инструмента.")
    lines.append(f"Исходная ошибка: {message[:300]}")
    return "\n".join(lines)


class WeakModelFastMCP(FastMCP):
    """FastMCP с одним повтором вызова после мягкого коэрсинга аргументов."""

    def _schema(self, name: str) -> dict:
        try:
            return self._tool_manager.get_tool(name).parameters or {}
        except Exception:  # noqa: BLE001 — неизвестный тулз упадёт выше
            return {}

    async def call_tool(self, name: str, arguments: dict):
        try:
            return await super().call_tool(name, arguments)
        except ToolError as first_error:
            message = str(first_error)
            # arguments={} (забытый required) тоже объясняем по-русски
            if "validation error" not in message or arguments is None:
                raise
            schema = self._schema(name)
            repaired = repair_arguments(schema, arguments)
            if repaired is None:
                raise ToolError(
                    explain_validation_error(name, schema, first_error))
            try:
                return await super().call_tool(name, repaired)
            except ToolError as second_error:
                raise ToolError(
                    explain_validation_error(name, schema, second_error))
