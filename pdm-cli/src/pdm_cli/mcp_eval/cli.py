"""CLI `pdm mcp-eval` — батарея качества слабомодельного агента (спека 142 D1).

Что: гоняет золотые кейсы (cases/*.yaml) агентным циклом tools/list →
OpenAI tools → tool_calls → tools/call против реальных MCP-серверов
(mcp-pdm :8015 read-профиль + defmcp :8016 write) и openai-compatible LLM.
Когда: приёмка слабомодельного контура (ADR-0058 п.4) — до включения верб
v2 в прод-агента; в CI не гоняется (env-гейт PDM_MCP_EVAL_LLM — без него
вежливый skip с кодом 0).
Возвращает: отчёт JSON + markdown summary; exit 0/1 по гейту ≥7/8 (D3).
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from .cases import load_cases
from .llm import LlmClient
from .mcp_client import McpEndpoint
from .report import (
    ACCEPTANCE_MIN,
    acceptance_ok,
    build_report,
    render_markdown,
    write_json,
    write_markdown,
)
from .runner import AgentRunner, CaseResult, default_system_prompt

CASES_DIR = Path(__file__).resolve().parent / "cases"


@click.command("mcp-eval")
@click.option(
    "--base", required=True,
    help="MCP read-эндпоинт агента, напр. http://mcp-pdm:8015/mcp"
         "?toolset=bp-admin (v2)")
@click.option(
    "--bp-base", default=None,
    help="MCP write-эндпоинт defmcp (:8016); кейсы с servers:[write] "
         "без него скипаются")
@click.option("--llm", "llm_base", default=None,
              help="OpenAI-compatible base URL (по умолчанию $PDM_MCP_EVAL_LLM)")
@click.option("--model", default=None,
              help="модель LLM (по умолчанию $PDM_MCP_EVAL_MODEL)")
@click.option("--llm-timeout", type=float, default=300.0, show_default=True,
              help="таймаут одного chat-вызова, с (CPU-прокси с длинным "
                   "префиллом — увеличивай)")
@click.option("--llm-temperature", type=float, default=0.1,
              show_default=True,
              help="temperature LLM (0 не ставь: Qwen-MoE на жадном "
                   "декодировании уходит в повторы tool_calls)")
@click.option("--case", "only_cases", multiple=True,
              help="прогнать только эти id кейсов (можно несколько раз)")
@click.option("--cases-dir", type=Path, default=None,
              help="каталог кейсов (по умолчанию — поставка cases/)")
@click.option("--system-prompt-file", type=Path, default=None,
              help="системный промпт (по умолчанию — инструкция агента "
                   "из templates/skills/pdm/pdm-edit-process.md)")
@click.option("--out", type=Path, default=None,
              help="JSON-отчёт (по умолчанию mcp-eval-report.json)")
@click.option("--md-out", type=Path, default=None,
              help="markdown summary (по умолчанию рядом с JSON)")
@click.pass_context
def mcp_eval(ctx, base, bp_base, llm_base, model, llm_timeout,
             llm_temperature, only_cases, cases_dir, system_prompt_file,
             out, md_out):
    """Батарея качества агента «БП-инженер»: 8 золотых кейсов US1–US6,
    метрики по спеке 142 (выбор тулза, аргументы после коэрсинга, итерации
    до зелёного, пик контекста, факты против ответов тулзов), гейт ≥7/8."""
    gate = os.environ.get("PDM_MCP_EVAL_LLM", "").strip()
    if not gate:
        click.echo(
            "SKIP: не задан env PDM_MCP_EVAL_LLM — батарея гоняется только "
            "по явному включению (нужна живая LLM; в CI не гоняется). "
            "Пример: PDM_MCP_EVAL_LLM=http://192.168.11.116:11434/v1 pdm "
            "mcp-eval --base … --model …")
        return 0

    llm_base = llm_base or gate
    model = model or os.environ.get("PDM_MCP_EVAL_MODEL", "").strip()
    if not model:
        raise click.ClickException(
            "укажи модель: --model <имя> (или env PDM_MCP_EVAL_MODEL); "
            "список моделей глянь curl <llm-base>/models")

    cases = load_cases(cases_dir or CASES_DIR)
    if only_cases:
        unknown = set(only_cases) - {c.id for c in cases}
        if unknown:
            raise click.ClickException(
                f"неизвестные кейсы: {', '.join(sorted(unknown))} "
                f"(доступны: {', '.join(c.id for c in cases)})")
        cases = [c for c in cases if c.id in only_cases]

    endpoints = {"read": McpEndpoint("read", base)}
    if bp_base:
        endpoints["write"] = McpEndpoint("write", bp_base)
    llm = LlmClient(llm_base, model, timeout=llm_timeout,
                    temperature=llm_temperature)
    system_prompt = (
        system_prompt_file.read_text(encoding="utf-8")
        if system_prompt_file else default_system_prompt())
    runner = AgentRunner(endpoints, llm, system_prompt=system_prompt)

    # Крах раннера в одном кейсе не роняет батарею: кейс красный с
    # причиной, остальные прогоняются, отчёт пишется (диагностика
    # приёмки D3 дороже мгновенного трейсбека).
    results = []
    for case in cases:
        try:
            results.append(runner.run_case(case))
        except Exception as exc:  # noqa: BLE001 — страховка поверх изоляции
            results.append(CaseResult(
                case=case, status="fail",
                fail_reasons=[f"раннер упал: {str(exc)[:300]}"]))
    report = build_report(results, {
        "base": base, "bp_base": bp_base, "llm": llm_base, "model": model,
        "cases_dir": str(cases_dir or CASES_DIR),
    })

    out = out or Path("mcp-eval-report.json")
    md_out = md_out or out.with_suffix(".md")
    write_json(report, out)
    write_markdown(report, md_out)

    click.echo(render_markdown(report))
    click.echo(f"JSON-отчёт: {out} · markdown: {md_out}")

    summary = report["summary"]
    ran = summary["ran"]
    healthy = acceptance_ok(report) if ran >= ACCEPTANCE_MIN \
        else summary["failed"] == 0
    if not healthy:
        ctx.exit(1)
