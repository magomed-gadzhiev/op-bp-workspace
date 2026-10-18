"""Отчёт батареи: JSON + markdown summary, приёмочный критерий ≥7/8 (D3)."""

from pdm_cli.mcp_eval.cases import EvalCase
from pdm_cli.mcp_eval.report import (
    ACCEPTANCE_MIN,
    acceptance_ok,
    build_report,
    render_markdown,
)
from pdm_cli.mcp_eval.runner import CaseResult


def _result(case_id, status):
    return CaseResult(
        case=EvalCase(id=case_id, title=case_id, servers=("read",), task="t"),
        status=status, skip_reason=None if status != "skip" else "нет write",
        final_answer="ответ", steps=[], tool_calls_total=1,
        tool_choice_ok=True, args_ok=True, green_iterations=None, green_ok=None,
        context_peak_tokens=1000, largest_tool_result_tokens=500,
        facts_ok=True, refuse_ok=None, fail_reasons=[])


def _report(statuses):
    results = [_result(f"case-{i}", s) for i, s in enumerate(statuses)]
    return build_report(results, {
        "base": "http://x/mcp", "bp_base": None,
        "llm": "http://y/v1", "model": "m"})


def test_acceptance_seven_of_eight():
    assert ACCEPTANCE_MIN == 7
    assert acceptance_ok(_report(["pass"] * 7 + ["fail"])) is True
    assert acceptance_ok(_report(["pass"] * 6 + ["fail"] * 2)) is False
    # скипнутые не в знаменателе: 7 прогнанных, все зелёные → гейт честен
    assert acceptance_ok(_report(["pass"] * 7 + ["skip"])) is True
    # прогнано меньше минимума — гейт не пройден
    assert acceptance_ok(_report(["pass"] * 6 + ["skip"] * 2)) is False


def test_markdown_summary_contains_table_and_meta():
    md = render_markdown(_report(["pass", "fail"]))
    assert "http://x/mcp" in md
    assert "http://y/v1" in md
    assert "case-0" in md and "case-1" in md
    assert "PASS" in md and "FAIL" in md
    assert "1/2" in md
    # метрики спеки — колонки таблицы
    lowered = md.lower()
    for column in ("тулз", "аргум", "пик", "факт"):
        assert column in lowered
    # проваленный кейс объяснён
    assert "НЕ ПРОЙДЕН" in md
