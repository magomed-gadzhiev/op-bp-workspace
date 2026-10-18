"""Агентный цикл раннера (перенос .scratch/agent_loop.py) и метрики
спеки 142 §«Батарея качества»: выбор тулза, аргументы после коэрсинга,
итерации до зелёного, пик контекста, граундинг фактов, отказ-пути US6."""

import json

from pdm_cli.mcp_eval.cases import EvalCase
from pdm_cli.mcp_eval.llm import LlmResponse, LlmToolCall
from pdm_cli.mcp_eval.mcp_client import ToolCallResult
from pdm_cli.mcp_eval.runner import (
    AgentRunner,
    check_grounding,
    default_system_prompt,
    extract_fact_tokens,
    is_argument_error,
)


def _case(**kw):
    base = dict(id="c", title="T", servers=("read",), task="Покажи список БП",
                max_steps=4)
    base.update(kw)
    return EvalCase(**base)


class FakeLlm:
    """Скриптованные ответы модели (реальный протокол chat → LlmResponse)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.seen_messages = []
        self.seen_tools = None

    def chat(self, messages, tools):
        self.seen_messages.append(messages)
        if self.seen_tools is None:
            self.seen_tools = tools
        return self.responses.pop(0)


def _assistant(*tool_calls):
    return LlmResponse(finish_reason="tool_calls", content="",
                       tool_calls=list(tool_calls), usage={}, ms=5)


def _final(text):
    return LlmResponse(finish_reason="stop", content=text,
                       tool_calls=[], usage={}, ms=5)


def _tc(name, args, call_id="call-1"):
    return LlmToolCall(id=call_id, name=name,
                       arguments_raw=json.dumps(args, ensure_ascii=False))


class FakeEndpoint:
    """MCP-эндпоинт без сети: инструменты + результаты по имени.

    Пресеты results[name]: {"obj": X} — успех; {"isError": True,
    "text": S} — ошибка; ToolCallResult — как есть (последовательность
    подменяется в SeqEndpoint)."""

    def __init__(self, name, tools, results=None):
        self.name = name
        self.tools = [{"name": t, "description": f"d {t}",
                       "inputSchema": {"type": "object"}} for t in tools]
        self.results = results or {}
        self.calls = []

    def list_tools(self):
        return self.tools

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        preset = self.results.get(name, {"obj": {"ok": True}})
        if isinstance(preset, ToolCallResult):
            preset.arguments = arguments
            return preset
        obj = preset.get("obj")
        is_error = bool(preset.get("isError"))
        text = preset.get("text")
        if text is None:
            text = obj if isinstance(obj, str) else json.dumps(
                obj, ensure_ascii=False, default=str)
        return ToolCallResult(
            tool=name, arguments=arguments,
            ok=None if is_error else obj, is_error=is_error,
            error_text=text if is_error else "", chars=len(text), ms=1)


class SeqEndpoint(FakeEndpoint):
    """Выдаёт заготовленные ToolCallResult по очереди (итерации до зелёного)."""

    def __init__(self, name, tools, seq):
        super().__init__(name, tools)
        self.seq = list(seq)

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        result = self.seq.pop(0)
        result.arguments = arguments
        return result


def _err_compile(n):
    return ToolCallResult(tool="bp_compile", arguments={}, ok=None,
                          is_error=True,
                          error_text=f"compile: ошибки в tasks/{n}.yaml",
                          chars=50, ms=1)


def _ok_compile():
    return ToolCallResult(tool="bp_compile", arguments={}, ok={"ok": True},
                          is_error=False, error_text="", chars=20, ms=1)


# ---------- сквозной агентный цикл ----------

def test_flow_routes_tools_across_two_servers():
    read = FakeEndpoint("read", ["list_business_processes"])
    write = FakeEndpoint("write", ["bp_edit_file"])
    llm = FakeLlm([
        _assistant(_tc("list_business_processes", {})),
        _assistant(_tc("bp_edit_file", {"path": "lem/process.yaml"})),
        _final("Готово: процесс обновлён"),
    ])
    runner = AgentRunner({"read": read, "write": write}, llm)
    result = runner.run_case(_case(
        servers=("read", "write"), tools_any=("bp_edit_file",),
        grounding=False))
    assert result.status == "pass", result.fail_reasons
    # маршрутизация по серверам: каждый тулз ушёл своему эндпоинту
    assert [c[0] for c in read.calls] == ["list_business_processes"]
    assert [c[0] for c in write.calls] == ["bp_edit_file"]
    assert result.tool_calls_total == 2
    assert result.final_answer.startswith("Готово")
    assert result.steps[-1].answer is not None


def test_tools_merged_from_both_servers_in_openai_format():
    read = FakeEndpoint("read", ["list_tasks"])
    write = FakeEndpoint("write", ["bp_compile"])
    llm = FakeLlm([
        _assistant(_tc("bp_compile", {"slug": "lem"})),
        _final("ok"),
    ])
    AgentRunner({"read": read, "write": write}, llm).run_case(
        _case(servers=("read", "write"), grounding=False))
    names = {t["function"]["name"] for t in llm.seen_tools}
    assert names == {"list_tasks", "bp_compile"}
    sample = llm.seen_tools[0]
    assert sample["type"] == "function"
    assert sample["function"]["parameters"]["type"] == "object"


def test_case_uses_only_listed_servers():
    read = FakeEndpoint("read", ["list_tasks"])
    write = FakeEndpoint("write", ["bp_compile"])
    llm = FakeLlm([_final("нет данных")])
    AgentRunner({"read": read, "write": write}, llm).run_case(
        _case(servers=("read",), grounding=False))
    names = {t["function"]["name"] for t in llm.seen_tools}
    assert names == {"list_tasks"}


def test_wrong_tool_choice_fails():
    read = FakeEndpoint("read", ["list_business_processes", "get_task"])
    llm = FakeLlm([
        _assistant(_tc("get_task", {"task_id": 1})),
        _final("Задача 1"),
    ])
    result = AgentRunner({"read": read}, llm).run_case(
        _case(tools_any=("list_business_processes",), grounding=False))
    assert result.status == "fail"
    assert result.tool_choice_ok is False
    assert any("list_business_processes" in r for r in result.fail_reasons)


def test_forbidden_tool_fails():
    read = FakeEndpoint("read", ["list_tasks", "get_user"])
    llm = FakeLlm([
        _assistant(_tc("get_user", {"user_id": 7})),
        _final("Пользователь 7"),
    ])
    result = AgentRunner({"read": read}, llm).run_case(_case(
        tools_any=("list_tasks",), forbidden_tools=("get_user",),
        grounding=False))
    assert result.status == "fail"
    assert any("get_user" in r for r in result.fail_reasons)


def test_forbidden_call_confirm_push_true_fails():
    write = FakeEndpoint("write", ["bp_push_sandbox"])
    write.results["bp_push_sandbox"] = {"obj": {"pushed": True}}
    llm = FakeLlm([
        _assistant(_tc("bp_push_sandbox",
                       {"slug": "lem", "confirm_push": True})),
        _final("Запушил в песочницу"),
    ])
    result = AgentRunner({"write": write}, llm).run_case(_case(
        servers=("write",), tools_any=(),
        forbidden_calls=(
            {"tool": "bp_push_sandbox", "args": {"confirm_push": True}},),
        grounding=False))
    assert result.status == "fail"
    assert any("confirm_push" in r for r in result.fail_reasons)


def test_push_refusal_path_passes():
    """US6: push без подтверждения → инструмент отказал, агент передал отказ."""
    write = FakeEndpoint("write", ["bp_push_sandbox"])
    write.results["bp_push_sandbox"] = {
        "isError": True,
        "text": "без явного подтверждения: пусть пользователь напишет "
                "«выкладывай в sandbox»"}
    llm = FakeLlm([
        _assistant(_tc("bp_push_sandbox", {"slug": "lem"})),
        _final("Не могу: нужно явное подтверждение человека для пуша в песочницу."),
    ])
    result = AgentRunner({"write": write}, llm).run_case(_case(
        servers=("write",), refuse=True,
        answer_markers_any=("подтвержд",),
        grounding=False))
    assert result.status == "pass", result.fail_reasons
    assert result.refuse_ok is True


# ---------- метрики ----------

def test_argument_error_detected():
    assert is_argument_error("Неверные аргументы: page_size — передай целое число")
    assert is_argument_error("Input should be a valid integer")
    assert not is_argument_error("Запуск БП #9 не найден")
    assert not is_argument_error("")


def test_args_ok_false_on_argument_error():
    read = FakeEndpoint("read", ["list_tasks"])
    read.results["list_tasks"] = {
        "isError": True,
        "text": "Неверные аргументы: business_process_id — передай целое число; "
                "ID — из list_business_processes"}
    llm = FakeLlm([
        _assistant(_tc("list_tasks", {"business_process_id": "пять"})),
        _final("Не получилось, нужно число"),
    ])
    result = AgentRunner({"read": read}, llm).run_case(
        _case(tools_any=("list_tasks",), grounding=False))
    assert result.status == "fail"
    assert result.args_ok is False
    assert any("аргумент" in r for r in result.fail_reasons)


def test_broken_json_arguments_do_not_crash():
    read = FakeEndpoint("read", ["list_tasks"])
    llm = FakeLlm([
        LlmResponse(finish_reason="tool_calls", content="", tool_calls=[
            LlmToolCall(id="c1", name="list_tasks",
                        arguments_raw='{"slug": lem')],
            usage={}, ms=1),
        _final("ok"),
    ])
    result = AgentRunner({"read": read}, llm).run_case(
        _case(tools_any=("list_tasks",), grounding=False))
    # битый JSON не рвёт цикл: вызов ушёл с пустыми аргументами
    assert read.calls and read.calls[0][1] == {}
    assert result.status == "pass"


def test_unknown_tool_recorded_as_error():
    read = FakeEndpoint("read", ["list_tasks"])
    llm = FakeLlm([
        _assistant(LlmToolCall(id="c1", name="bp_hallucinated_tool",
                               arguments_raw="{}")),
        _final("нет такого инструмента"),
    ])
    result = AgentRunner({"read": read}, llm).run_case(
        _case(grounding=False))
    step = result.steps[0]
    assert step.tool_calls[0]["is_error"] is True
    assert "bp_hallucinated_tool" in step.tool_calls[0]["error_text"]


def test_step_limit_exhaustion_fails():
    read = FakeEndpoint("read", ["list_tasks"])
    llm = FakeLlm([_assistant(_tc("list_tasks", {})) for _ in range(10)])
    result = AgentRunner({"read": read}, llm).run_case(
        _case(max_steps=3, grounding=False))
    assert result.status == "fail"
    assert result.final_answer is None
    assert any("шаг" in r for r in result.fail_reasons)
    assert len(result.steps) == 3


def test_green_iterations_counted():
    seq = [_err_compile("01"), _err_compile("02"), _ok_compile()]
    llm = FakeLlm([
        _assistant(_tc("bp_compile", {"slug": "lem"}, "1")),
        _assistant(_tc("bp_compile", {"slug": "lem"}, "2")),
        _assistant(_tc("bp_compile", {"slug": "lem"}, "3")),
        _final("compile зелёный"),
    ])
    write = SeqEndpoint("write", ["bp_compile"], seq)
    result = AgentRunner({"write": write}, llm).run_case(_case(
        servers=("write",), green_tools=("bp_compile",),
        max_green_iterations=3, grounding=False))
    assert result.status == "pass", result.fail_reasons
    assert result.green_iterations == 3

    # тот же паттерн с бюджетом 2 — провал
    seq2 = [_err_compile("01"), _err_compile("02"), _ok_compile()]
    llm2 = FakeLlm([
        _assistant(_tc("bp_compile", {"slug": "lem"}, "1")),
        _assistant(_tc("bp_compile", {"slug": "lem"}, "2")),
        _assistant(_tc("bp_compile", {"slug": "lem"}, "3")),
        _final("compile зелёный"),
    ])
    write2 = SeqEndpoint("write", ["bp_compile"], seq2)
    result2 = AgentRunner({"write": write2}, llm2).run_case(_case(
        servers=("write",), green_tools=("bp_compile",),
        max_green_iterations=2, grounding=False))
    assert result2.status == "fail"
    assert result2.green_ok is False


def test_context_peak_grows_with_tool_results():
    read = FakeEndpoint("read", ["list_tasks"])
    read.results["list_tasks"] = {"obj": {"items": ["x" * 5000]}}
    llm = FakeLlm([
        _assistant(_tc("list_tasks", {})),
        _assistant(_tc("list_tasks", {}, "2")),
        _final("готово"),
    ])
    result = AgentRunner({"read": read}, llm).run_case(
        _case(grounding=False))
    chars = [s.context_chars for s in result.steps]
    assert chars == sorted(chars)  # монотонный рост
    assert chars[1] > chars[0] + 4000  # результат тулза в контексте
    assert result.context_peak_tokens == round(chars[-1] / 3.5)
    assert result.largest_tool_result_tokens >= round(5000 / 3.5)


# ---------- граундинг фактов ----------

def test_extract_fact_tokens_digits_and_quotes():
    text = "Запуск 40419 падал на шаге 3, скрипт «calc_score» из лим 12"
    tokens = extract_fact_tokens(text)
    assert "40419" in tokens
    assert "calc_score" in tokens
    assert "3" not in tokens  # одиночные цифры (маркеры списка) не считаем


def test_grounding_ok_when_facts_from_tools():
    ok, phantom = check_grounding(
        "Запуск 40419 упал", "запуск 40419 … #40419 error", allow=())
    assert ok and phantom == []


def test_grounding_detects_hallucinated_id():
    ok, phantom = check_grounding(
        "Запуск 777 упал на шаге", "тут только 40419", allow=())
    assert not ok and phantom == ["777"]


def test_grounding_allow_whitelists():
    ok, phantom = check_grounding(
        "p95 = 95", "длительности p95", allow=("95",))
    assert ok and phantom == []


def test_grounding_task_text_is_source():
    # задание само является источником (id из вопроса валиден)
    ok, _ = check_grounding("про 999999999", "вопрос про 999999999", allow=())
    assert ok


def test_facts_include_and_markers_any():
    read = FakeEndpoint("read", ["list_tasks"])
    llm = FakeLlm([_final("Всё хорошо")])
    result = AgentRunner({"read": read}, llm).run_case(_case(
        facts_include=("лем",), grounding=False))
    assert result.status == "fail"
    assert result.facts_ok is False

    llm2 = FakeLlm([_final("В БП лем всё хорошо")])
    result2 = AgentRunner({"read": read}, llm2).run_case(_case(
        facts_include=("лем",), answer_markers_any=("хорошо", "отлично"),
        grounding=False))
    assert result2.status == "pass", result2.fail_reasons

    llm3 = FakeLlm([_final("В БП лем всё плохо")])
    result3 = AgentRunner({"read": read}, llm3).run_case(_case(
        facts_include=("лем",), answer_markers_any=("хорошо", "отлично"),
        grounding=False))
    assert result3.status == "fail"
    assert any("маркер" in r for r in result3.fail_reasons)


def test_hallucinated_fact_in_final_answer_fails():
    read = FakeEndpoint("read", ["list_business_processes"])
    read.results["list_business_processes"] = {
        "obj": {"items": [{"id": 12, "name": "ЛЕМ", "slug": "lem"}]}}
    llm = FakeLlm([
        _assistant(_tc("list_business_processes", {})),
        _final("В базе 3 процесса: ЛЕМ (id 12), Плотва (id 77), Сборка (id 90)"),
    ])
    result = AgentRunner({"read": read}, llm).run_case(
        _case(tools_any=("list_business_processes",)))
    assert result.status == "fail"
    assert result.facts_ok is False
    # 12 — граундед (из ответа тулза), 77 и 90 — галлюцинации
    assert "77" in " ".join(result.fail_reasons) or "90" in " ".join(
        result.fail_reasons)


# ---------- системный промпт и skip ----------

def test_default_system_prompt_from_agent_instruction():
    prompt = default_system_prompt()
    assert not prompt.startswith("---")  # frontmatter срезан
    assert "БП-инженер" in prompt
    assert "bp_test" in prompt


def test_default_system_prompt_covers_v2_surface():
    """Батарея мерит прода-агента: инструкция обязана рассказывать про всю
    поверхность v2 (спека 142 D2) — граундинг и отчёты, не только скрипты.
    Иначе кейсы 2/3/5/6 проверяют агента, который о вербах не знает."""
    prompt = default_system_prompt()
    for verb in ("bp_find_examples", "bp_field_reference",
                 "bp_run_report", "bp_bottlenecks_report",
                 "bp_script_check", "bp_test"):
        assert verb in prompt, f"инструкция агента не упоминает {verb}"


def test_case_skipped_when_server_missing():
    read = FakeEndpoint("read", ["list_tasks"])
    llm = FakeLlm([])
    runner = AgentRunner({"read": read}, llm)
    result = runner.run_case(_case(servers=("read", "write")))
    assert result.status == "skip"
    assert "write" in (result.skip_reason or "")


# ---------- изоляция сбоев LLM (приёмка D3: отчёт обязан выжить) ----------

def test_llm_failure_fails_case_not_battery():
    """Сбой LLM-эндпоинта (таймаут/5xx/битый JSON) изолируется кейсом:
    run_case возвращает fail с причиной, а не роняет весь прогон —
    метрики остальных кейсов и отчёт сохраняются."""
    read = FakeEndpoint("read", ["list_tasks"])

    class ExplodingLlm:
        def chat(self, messages, tools):
            raise RuntimeError("HTTP 503: model overloaded")

    result = AgentRunner({"read": read}, ExplodingLlm()).run_case(
        _case(grounding=False))
    assert result.status == "fail"
    assert result.final_answer is None
    assert any("LLM" in r for r in result.fail_reasons)
    assert any("503" in r for r in result.fail_reasons)


def test_llm_failure_mid_case_keeps_partial_steps():
    """Сбой на середине кейса: уже сделанные шаги и tool-calls остаются
    в результате (диагностика частичного прогона)."""
    read = FakeEndpoint("read", ["list_tasks"])

    class HalfLlm:
        def __init__(self):
            self.n = 0

        def chat(self, messages, tools):
            self.n += 1
            if self.n == 1:
                return _assistant(_tc("list_tasks", {}))
            raise RuntimeError("read timeout")

    result = AgentRunner({"read": read}, HalfLlm()).run_case(
        _case(grounding=False))
    assert result.status == "fail"
    assert len(result.steps) == 1
    assert result.tool_calls_total == 1
    assert result.final_answer is None


def test_loop_detected_on_step_limit():
    """3+ одинаковых шага подряд → note на шаге и fail_reason "loop"
    (узор прод-прогонов 07.10: модель кружит на граундинге, исчерпав лимит)."""
    read = FakeEndpoint("read", ["bp_find_examples"])
    llm = FakeLlm([
        _assistant(_tc("bp_find_examples", {"query": "test case"}, str(i)))
        for i in range(5)
    ])
    result = AgentRunner({"read": read}, llm).run_case(
        _case(max_steps=5, grounding=False))
    assert result.status == "fail"
    assert any("loop" in r for r in result.fail_reasons)
    loop_notes = [n for s in result.steps for n in s.notes if "loop" in n]
    assert loop_notes and "bp_find_examples" in loop_notes[0]
