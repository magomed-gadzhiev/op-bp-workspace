"""Кейсы батареи качества (cases/*.yaml, спека 142 §«Батарея качества»).

Что: YAML-кейс = задание агенту + ожидания (какие тулзы, отказ-путь,
граундинг фактов, зелёные итерации). servers: read — mcp-pdm:8015,
write — defmcp:8016.
Когда: `pdm mcp-eval` грузит каталог cases/ (или --cases-dir).
Возвращает: EvalCase-датаклассы с русскими ошибками валидации.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

KNOWN_SERVERS = ("read", "write")


@dataclass
class EvalCase:
    """Один золотой кейс: задание + ожидания (метрики считает раннер)."""

    id: str
    title: str
    servers: Tuple[str, ...]
    task: str
    max_steps: int = 8
    # ≥1 вызов из списка (пусто — любой тулз); выбор тулза
    tools_any: Tuple[str, ...] = ()
    # вызов этих тулзов = провал кейса
    forbidden_tools: Tuple[str, ...] = ()
    # запрет пары тулз+аргументы (HITL-граница: тулз с конкретными args)
    forbidden_calls: Tuple[Dict[str, Any], ...] = ()
    # метрика «итераций до зелёного»: вызовы этих тулзов до первого
    # не-ошибочного результата
    green_tools: Tuple[str, ...] = ()
    # 0 — метрика не проверяется; N — зелёный обязан наступить ≤ N вызовов
    max_green_iterations: int = 0
    # ВСЕ подстроки обязаны встретиться в финальном ответе (case-insensitive)
    facts_include: Tuple[str, ...] = ()
    # ХОТЯ БЫ ОДНА подстрока в финальном ответе (отказ-маркеры и т.п.)
    answer_markers_any: Tuple[str, ...] = ()
    # ждём отказ (HITL): финальный ответ содержит маркер отказа
    refuse: bool = False
    # числа/ID/«кавычки» финального ответа обязаны быть в ответах тулзов
    # или в тексте задания (анти-галлюцинация)
    grounding: bool = True
    # литералы, разрешённые без граундинга (счётчики, номера шагов кейса)
    grounding_allow: Tuple[str, ...] = ()


def _as_tuple(value: Any) -> Tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


def load_case(path: Path) -> EvalCase:
    """Загрузить один кейс; ошибки валидации — русские, с именем кейса."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    where = f"кейс {path.name}"
    for key in ("id", "title", "servers", "task"):
        if not raw.get(key):
            raise ValueError(f"{where}: нет обязательного поля '{key}'")
    servers = _as_tuple(raw["servers"])
    unknown = [s for s in servers if s not in KNOWN_SERVERS]
    if unknown:
        raise ValueError(
            f"{where}: неизвестные серверы {unknown} "
            f"(доступны: {', '.join(KNOWN_SERVERS)})")
    expect = raw.get("expect") or {}
    forbidden_calls = tuple(
        {"tool": item.get("tool"), "args": item.get("args") or {}}
        for item in expect.get("forbidden_calls") or [])
    return EvalCase(
        id=str(raw["id"]),
        title=str(raw["title"]),
        servers=tuple(servers),
        task=str(raw["task"]),
        max_steps=int(raw.get("max_steps", 8)),
        tools_any=_as_tuple(expect.get("tools_any")),
        forbidden_tools=_as_tuple(expect.get("forbidden_tools")),
        forbidden_calls=forbidden_calls,
        green_tools=_as_tuple(expect.get("green_tools")),
        max_green_iterations=int(expect.get("max_green_iterations", 0)),
        facts_include=_as_tuple(expect.get("facts_include")),
        answer_markers_any=_as_tuple(expect.get("answer_markers_any")),
        refuse=bool(expect.get("refuse", False)),
        grounding=bool(expect.get("grounding", True)),
        grounding_allow=_as_tuple(expect.get("grounding_allow")),
    )


def load_cases(directory: Path) -> List[EvalCase]:
    """Все кейсы каталога (sorted по имени файла); id уникальны."""
    cases = [load_case(path) for path in sorted(directory.glob("*.yaml"))]
    seen: Dict[str, Path] = {}
    for case in cases:
        if case.id in seen:
            raise ValueError(
                f"дубликат id кейса '{case.id}' "
                f"(уже был в {seen[case.id].name})")
        seen[case.id] = Path(case.id)
    return cases
