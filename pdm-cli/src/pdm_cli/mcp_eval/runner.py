"""Агентный цикл батареи (перенос .scratch/agent_loop.py в репо, спека 142 D1).

Что: цикл как у LibreChat-агента — tools/list MCP-серверов → OpenAI tools →
tool_calls модели → tools/call в MCP → результат обратно в чат; по каждому
кейсу считает метрики спеки (выбор тулза, аргументы после коэрсинга,
итерации до зелёного, пик контекста, факты против ответов тулзов).
Когда: `pdm mcp-eval` (env-гейт PDM_MCP_EVAL_LLM) и юнит-тесты на фейках.
Возвращает: CaseResult (status pass/fail/skip + метрики + причины провала).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .cases import EvalCase
from .llm import LlmClient
from .mcp_client import McpEndpoint, ToolCallResult

# Оценка токенов как в дизайн-сессии: ~3.5 симв./токен для русско-английского
# JSON-микса.
CHARS_PER_TOKEN = 3.5
# Результат тулза в контекст модели режем до 60k символов (перенос agent_loop).
TOOL_RESULT_CHAR_CAP = 60000

# Аргументная ошибка = «коэрсинг не спас»: после серверного ремонта аргументов
# вызов всё равно упал валидацией (русский текст по ADR-0058 либо остаточный
# pydantic-английский).
ARG_ERROR_MARKERS = (
    "неверные аргументы",
    "input should be",
    "unable to parse",
    "field required",
)
# Маркеры отказа-ответа (HITL US6): агент передал человеку требование
# подтверждения, а не «успешно запушил».
REFUSAL_MARKERS = (
    "подтвержд", "отказ", "нельзя", "не буду", "не стану", "отмен",
    "явной команд", "спроси человека",
)
_FACT_TOKEN_RE = re.compile(r"\d{2,}|«([^»]{1,64})»")


SYSTEM_PROMPT_FALLBACK = (
    "Ты — БП-инженер. Правишь определения бизнес-процессов через MCP-тулзы "
    "сервера pdm-bp, состояние читаешь тулзами pdm-bp-admin. Не выдумывай ID "
    "и пути: не знаешь — сначала вызови list_* / bp_list_files. Push в "
    "песочницу — только по явному подтверждению человека (confirm_push). "
    "Отвечай по-русски, кратко."
)


def default_system_prompt() -> str:
    """Системный промпт по умолчанию — инструкция прода-агента «БП-инженер»
    (templates/skills/pdm/pdm-edit-process.md, YAML-frontmatter срезается):
    батарея обязана мерить того же агента, что работает в LibreChat."""
    path = (Path(__file__).resolve().parents[1] / "templates" / "skills"
            / "pdm" / "pdm-edit-process.md")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return SYSTEM_PROMPT_FALLBACK
    if text.startswith("---"):
        _, _, body = text.split("---", 2)
        return body.strip()
    return text.strip()


def extract_fact_tokens(text: str) -> List[str]:
    """Факто-подобные токены ответа: числа от 2 знаков (ID, часы, p50…) и
    строки в «кавычках» (имена). Одиночные цифры пропускаем — это маркеры
    списков и мелкие счётчики."""
    tokens: List[str] = []
    for match in _FACT_TOKEN_RE.finditer(text or ""):
        token = match.group(1) if match.group(1) is not None else match.group(0)
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def check_grounding(final_answer: str, sources_text: str,
                    allow: Sequence[str] = ()) -> Tuple[bool, List[str]]:
    """Анти-галлюцинация: каждый факто-токен финального ответа обязан
    встречаться в источниках (задание + ответы тулзов = данные из БД).
    Возвращает (ok, фантомы)."""
    haystack = (sources_text or "").lower()
    phantom = [token for token in extract_fact_tokens(final_answer)
               if token.lower() not in haystack
               and token.lower() not in {a.lower() for a in allow}]
    return (not phantom), phantom


def is_argument_error(error_text: str) -> bool:
    lowered = (error_text or "").lower()
    return any(marker in lowered for marker in ARG_ERROR_MARKERS)


@dataclass
class CaseStep:
    """Один round-trip к модели: контекст на входе + сделанные tool_calls."""

    step: int
    finish_reason: Optional[str] = None
    answer: Optional[str] = None
    context_chars: int = 0
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class CaseResult:
    case: EvalCase
    status: str = "fail"          # pass | fail | skip
    skip_reason: Optional[str] = None
    final_answer: Optional[str] = None
    steps: List[CaseStep] = field(default_factory=list)
    tool_calls_total: int = 0
    tool_choice_ok: bool = True
    args_ok: bool = True
    green_iterations: Optional[int] = None
    green_ok: Optional[bool] = None
    context_peak_tokens: int = 0
    largest_tool_result_tokens: int = 0
    facts_ok: Optional[bool] = None
    refuse_ok: Optional[bool] = None
    fail_reasons: List[str] = field(default_factory=list)


def _result_text(result: ToolCallResult) -> str:
    if result.is_error:
        return result.error_text
    if isinstance(result.ok, str):
        return result.ok
    return json.dumps(result.ok, ensure_ascii=False, default=str)


class AgentRunner:
    """Агент с несколькими MCP-серверами (как прод-агент: bp-admin + defmcp)."""

    def __init__(self, endpoints: Dict[str, McpEndpoint], llm: LlmClient,
                 system_prompt: Optional[str] = None):
        self.endpoints = endpoints
        self.llm = llm
        self.system_prompt = system_prompt if system_prompt is not None \
            else default_system_prompt()

    # -- подготовка ---------------------------------------------------------

    def _tools_for(self, servers: Sequence[str]
                   ) -> Tuple[List[Dict[str, Any]], Dict[str, McpEndpoint]]:
        tools: List[Dict[str, Any]] = []
        routing: Dict[str, McpEndpoint] = {}
        for server in servers:
            endpoint = self.endpoints[server]
            for raw in endpoint.list_tools():
                name = raw["name"]
                routing[name] = endpoint
                tools.append({
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": (raw.get("description") or "")[:4000],
                        "parameters": raw.get("inputSchema") or {
                            "type": "object", "properties": {}},
                    },
                })
        return tools, routing

    # -- основной цикл ------------------------------------------------------

    def run_case(self, case: EvalCase) -> CaseResult:
        missing = [s for s in case.servers if s not in self.endpoints]
        if missing:
            return CaseResult(
                case=case, status="skip",
                skip_reason=f"нет сервера: {', '.join(missing)} "
                            f"(передай --bp-base для write-кейсов)")

        try:
            tools, routing = self._tools_for(case.servers)
        except Exception as exc:  # noqa: BLE001 — сбой соединения = fail кейса
            return CaseResult(case=case, status="fail",
                              fail_reasons=[f"tools/list: {exc}"])

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": case.task},
        ]
        result = CaseResult(case=case)
        calls: List[Tuple[ToolCallResult, bool]] = []  # (результат, арг.ошибка)
        sources = [case.task]
        peak_chars = 0
        prev_sig: Tuple[Tuple[str, str], ...] = ()
        same_sig_steps = 0
        looped = False

        for step_no in range(1, case.max_steps + 1):
            context_chars = len(json.dumps(messages, ensure_ascii=False))
            peak_chars = max(peak_chars, context_chars)
            try:
                response = self.llm.chat(messages, tools)
            except Exception as exc:  # noqa: BLE001 — сбой LLM = fail кейса,
                # не всей батареи: диагностика прогона обязана дожить до
                # отчёта (таймаут/5xx/переполнение контекста модели)
                result.fail_reasons.append(
                    f"сбой LLM на шаге {step_no}: {str(exc)[:300]}")
                break
            step = CaseStep(step=step_no,
                            finish_reason=response.finish_reason,
                            context_chars=context_chars)

            if not response.tool_calls:
                result.final_answer = response.content
                step.answer = (response.content or "")[:2000]
                result.steps.append(step)
                break

            # Детект циклов (чистая диагностика, поведение не меняем):
            # 3+ шага подряд с идентичным набором tool_calls = модель
            # застряла (типовой узор прод-прогонов 07.10 на кейсах 03/04).
            sig = tuple(sorted((tc.name, (tc.arguments_raw or "").strip())
                               for tc in response.tool_calls))
            same_sig_steps = same_sig_steps + 1 if sig == prev_sig else 1
            prev_sig = sig
            if same_sig_steps >= 3:
                looped = True
                if same_sig_steps == 3:
                    step.notes.append(
                        "loop: три шага подряд идентичные tool_calls ("
                        + ", ".join(name for name, _ in sig) + ")")

            messages.append({
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [{
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.name,
                                 "arguments": tc.arguments_raw},
                } for tc in response.tool_calls],
            })
            for tc in response.tool_calls:
                try:
                    arguments = json.loads(tc.arguments_raw or "{}")
                except ValueError:
                    arguments = {}
                    step.notes.append(
                        f"битый JSON аргументов: {tc.arguments_raw[:200]}")
                endpoint = routing.get(tc.name)
                if endpoint is None:
                    call_result = ToolCallResult(
                        tool=tc.name, arguments=arguments, is_error=True,
                        error_text=f"неизвестный инструмент {tc.name} "
                                   f"(нет в подключённых серверах)")
                else:
                    call_result = endpoint.call_tool(tc.name, arguments)
                text = _result_text(call_result)
                sources.append(text)
                calls.append((call_result, is_argument_error(text)
                              and call_result.is_error))
                step.tool_calls.append({
                    "tool": tc.name, "args": arguments,
                    "is_error": call_result.is_error,
                    "error_text": (call_result.error_text or "")[:300],
                    "chars": call_result.chars, "ms": call_result.ms,
                })
                messages.append({
                    "role": "tool", "tool_call_id": tc.id, "name": tc.name,
                    "content": text[:TOOL_RESULT_CHAR_CAP],
                })
            result.steps.append(step)
        else:
            result.fail_reasons.append(
                f"лимит шагов ({case.max_steps}) исчерпан без финального "
                f"ответа")
            if looped:
                result.fail_reasons.append(
                    "loop: модель повторяла идентичные tool_calls "
                    "(notes шагов)")

        self._evaluate(case, result, calls, sources, peak_chars)
        return result

    # -- метрики ------------------------------------------------------------

    def _evaluate(self, case: EvalCase, result: CaseResult,
                  calls: List[Tuple[ToolCallResult, bool]],
                  sources: List[str], peak_chars: int) -> None:
        results = [c for c, _ in calls]
        arg_errors = [c for c, is_arg_err in calls if is_arg_err]
        result.tool_calls_total = len(results)

        # выбор тулза
        called = [c.tool for c in results]
        if case.tools_any:
            result.tool_choice_ok = any(t in case.tools_any for t in called)
            if not result.tool_choice_ok:
                result.fail_reasons.append(
                    "ожидались тулзы " + ", ".join(case.tools_any)
                    + f"; вызваны: {', '.join(called) or '—'}")
        hit_forbidden = sorted(set(called) & set(case.forbidden_tools))
        if hit_forbidden:
            result.tool_choice_ok = False
            result.fail_reasons.append(
                f"вызовы запрещённых тулзов: {', '.join(hit_forbidden)}")
        for forbidden in case.forbidden_calls:
            tool, args = forbidden["tool"], forbidden.get("args") or {}
            for call in results:
                if call.tool != tool:
                    continue
                if all(call.arguments.get(k) == v for k, v in args.items()):
                    result.tool_choice_ok = False
                    result.fail_reasons.append(
                        f"запрещённый вызов {tool} с аргументами "
                        f"{json.dumps(args, ensure_ascii=False)} (HITL-гейт)")

        # аргументы после коэрсинга
        result.args_ok = not arg_errors
        if arg_errors:
            result.fail_reasons.append(
                f"ошибки аргументов после коэрсинга: {len(arg_errors)} "
                f"вызов(ов) упали валидацией")

        # итерации до зелёного
        if case.green_tools:
            green_iterations = 0
            green_hit = False
            for call in results:
                if call.tool not in case.green_tools:
                    continue
                green_iterations += 1
                if not call.is_error:
                    green_hit = True
                    break
            result.green_iterations = green_iterations if green_hit else None
            if case.max_green_iterations:
                result.green_ok = (
                    green_hit
                    and green_iterations <= case.max_green_iterations)
                if not result.green_ok:
                    expected = ", ".join(case.green_tools)
                    got = (f"{green_iterations}-й вызов"
                           if green_hit else "не наступил")
                    result.fail_reasons.append(
                        f"зелёный {expected} не достигнут за "
                        f"{case.max_green_iterations} итераций ({got})")

        # контекст
        result.context_peak_tokens = round(peak_chars / CHARS_PER_TOKEN)
        result.largest_tool_result_tokens = round(
            max((c.chars for c in results), default=0) / CHARS_PER_TOKEN)

        # финальный ответ и факты
        answer = result.final_answer
        if answer is None:
            return  # причина уже добавлена (лимит шагов)
        lowered = answer.lower()
        if case.facts_include:
            missing = [s for s in case.facts_include
                       if s.lower() not in lowered]
            if missing:
                result.fail_reasons.append(
                    "в финальном ответе нет: " + ", ".join(missing))
        markers_ok = True
        if case.answer_markers_any:
            markers_ok = any(m.lower() in lowered
                             for m in case.answer_markers_any)
            if not markers_ok:
                result.fail_reasons.append(
                    "нет ни одного маркера из: "
                    + ", ".join(case.answer_markers_any))
        if case.refuse:
            markers = case.answer_markers_any or REFUSAL_MARKERS
            result.refuse_ok = any(m.lower() in lowered for m in markers)
            if not result.refuse_ok:
                result.fail_reasons.append(
                    "ожидался отказ (HITL) с маркером подтверждения — "
                    "ответ его не содержит")
        grounding_ok = True
        if case.grounding:
            grounding_ok, phantom = check_grounding(
                answer, "\n".join(sources), case.grounding_allow)
            if phantom:
                result.fail_reasons.append(
                    "факты не из ответов тулзов (галлюцинации): "
                    + ", ".join(phantom))
        result.facts_ok = (not case.facts_include
                           or all(s.lower() in lowered
                                  for s in case.facts_include)) \
            and markers_ok and grounding_ok

        # вердикт
        result.status = "pass" if not result.fail_reasons else "fail"
