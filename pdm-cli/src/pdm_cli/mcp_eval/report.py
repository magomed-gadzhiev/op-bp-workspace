"""Отчёт батареи: JSON (полный лог) + markdown summary; гейт ≥7/8 (спека D3).

Что: строит отчёт по CaseResult-ам — сводка (passed/failed/skipped,
приёмочный гейт), таблица кейсов с метриками спеки, пошаговый журнал.
Когда: `pdm mcp-eval` после прогона всех кейсов.
Возвращает: dict для json.dump и строку markdown.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .runner import CaseResult

# Спека 142 §«Батарея качества» (D3): приёмочный гейт — ≥7 из 8 золотых
# кейсов зелёные (прогон на живой Qwen3.6-35B до включения верб в прод-агент).
ACCEPTANCE_MIN = 7


def case_to_dict(result: CaseResult) -> Dict[str, Any]:
    return {
        "id": result.case.id,
        "title": result.case.title,
        "status": result.status,
        "skip_reason": result.skip_reason,
        "final_answer": result.final_answer,
        "tool_calls_total": result.tool_calls_total,
        "tool_choice_ok": result.tool_choice_ok,
        "args_ok": result.args_ok,
        "green_iterations": result.green_iterations,
        "green_ok": result.green_ok,
        "context_peak_tokens": result.context_peak_tokens,
        "largest_tool_result_tokens": result.largest_tool_result_tokens,
        "facts_ok": result.facts_ok,
        "refuse_ok": result.refuse_ok,
        "fail_reasons": result.fail_reasons,
        "steps": [{
            "step": s.step,
            "finish_reason": s.finish_reason,
            "answer": s.answer,
            "context_chars": s.context_chars,
            "notes": s.notes,
            "tool_calls": s.tool_calls,
        } for s in result.steps],
    }


def build_report(results: List[CaseResult], meta: Dict[str, Any]
                 ) -> Dict[str, Any]:
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    skipped = sum(1 for r in results if r.status == "skip")
    return {
        "meta": meta,
        "summary": {
            "passed": passed, "failed": failed, "skipped": skipped,
            "total": len(results), "ran": passed + failed,
            "acceptance_min": ACCEPTANCE_MIN,
            "acceptance_ok": passed >= ACCEPTANCE_MIN,
        },
        "cases": [case_to_dict(r) for r in results],
    }


def acceptance_ok(report: Dict[str, Any]) -> bool:
    """≥7 зелёных из прогнанных (скипы не в знаменателе: кейс без сервера
    не проверен, а не провален)."""
    return report["summary"]["passed"] >= ACCEPTANCE_MIN


def _mark(value: Any) -> str:
    if value is None:
        return "—"
    return "✓" if value else "✗"


def render_markdown(report: Dict[str, Any]) -> str:
    meta = report["meta"]
    summary = report["summary"]
    verdict = "✅ ПРОЙДЕН" if acceptance_ok(report) else "❌ НЕ ПРОЙДЕН"
    note = ""
    if summary["ran"] < 8:
        note = (f" (прогнано подмножество {summary['ran']}/{summary['total']} —"
                f" приёмка оценивается на всех 8 золотых кейсах)")
    lines = [
        "# Батарея качества pdm mcp-eval (спека 142, волна D)",
        "",
        f"- read MCP: `{meta.get('base', '—')}`",
        f"- write MCP (defmcp): `{meta.get('bp_base') or '—'}`",
        f"- LLM: `{meta.get('llm', '—')}` · модель: `{meta.get('model', '—')}`",
        f"- Итог: **{summary['passed']}/{summary['ran']}** зелёных"
        f" (скипов: {summary['skipped']}) · приёмочный гейт "
        f"≥{ACCEPTANCE_MIN} из прогнанных (спека D3): {verdict}{note}",
        "",
        "| Кейс | Статус | Тулз | Аргум | Зелёный | Пик ток | Факты |"
        " Причины провала |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for case in report["cases"]:
        green = ("—" if case["green_iterations"] is None
                 else f"{case['green_iterations']}"
                 + ("" if case.get("green_ok") else " (бюджет)"))
        reasons = "; ".join(case["fail_reasons"])[:200] or "—"
        lines.append(
            f"| {case['id']} | {case['status'].upper()} "
            f"| {_mark(case['tool_choice_ok'])} "
            f"| {_mark(case['args_ok'])} | {green} "
            f"| {case['context_peak_tokens']} "
            f"| {_mark(case['facts_ok'])} | {reasons} |")
    lines += [
        "",
        "Метрики: тулз — выбор инструмента; аргум — аргументы после "
        "коэрсинга; зелёный — итераций до зелёного compile/test; "
        "пик ток — максимум контекста (~3.5 симв./токен); факты — "
        "финальный ответ против ответов тулзов (галлюцинации).",
    ]
    return "\n".join(lines) + "\n"


def write_json(report: Dict[str, Any], path: Path) -> None:
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(report: Dict[str, Any], path: Path) -> None:
    path.write_text(render_markdown(report), encoding="utf-8")
