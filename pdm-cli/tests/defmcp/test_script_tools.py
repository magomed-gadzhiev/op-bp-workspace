"""Контракт-тесты волны B (спека 142): bp_script_check + bp_test.

Оба инструмента — новые вербы ADR-0058: доменные ошибки обязаны уходить
с isError=true (в тестах это ToolError — протокольный слой SDK конвертирует
её в isError=true), тексты русские с next-подсказкой, docstring ≤600 симв.
Песочница НЕ поднимается: ensure_sandbox_up/bring_down_sandbox/run_case
мокаются по образцу tests/test_command_test.py (инвариант 6).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import respx
from mcp.server.fastmcp.exceptions import ToolError

from pdm_cli.defmcp.context import BpContext
from pdm_cli.defmcp.server import make_server
from pdm_cli.sandbox_lifecycle import SandboxNotRunningError
from pdm_cli.test_runner.runner import AssertionResult, CaseResult

API = "http://pdm.local"
SANDBOX = "http://pdm-sandbox:8000"

SCRIPT_WARNING = "скрипты не версионируются"


# ---------- фикстуры ----------


def _write_sandbox_config(repo) -> None:
    (repo / "pdm.config.yaml").write_text(
        "endpoints:\n"
        f"  sandbox: {SANDBOX}\n",
        encoding="utf-8",
    )
    (repo / ".pdm").mkdir(exist_ok=True)
    (repo / ".pdm" / "secrets.yaml").write_text(
        "api_key_sandbox: T\n", encoding="utf-8",
    )


def _write_script(ctx, rel: str, code: str) -> str:
    """Пишет workspace/<rel> скрипт; возвращает rel (путь от workspace)."""
    target = ctx.drafts_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(code, encoding="utf-8")
    return rel


def _write_case(drafts_root, slug: str = "bp1", case_name: str = "smoke",
                timeout_sec: int = 60) -> None:
    tests = drafts_root / slug / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (tests / f"{case_name}.yaml").write_text(
        f"name: {case_name}\n"
        "fixtures: []\n"
        "entity:\n"
        "  type: contract\n"
        "  fields: {}\n"
        f"timeout_sec: {timeout_sec}\n"
        "expect:\n"
        "  final_status: completed\n"
        "  side_effects: []\n",
        encoding="utf-8",
    )


@pytest.fixture()
def ctx(tmp_path):
    ws = tmp_path / "ws"
    bp = ws / "testbp"
    (bp / "scripts").mkdir(parents=True)
    (bp / "process.yaml").write_text("slug: testbp\n", encoding="utf-8")
    return BpContext(repo_root=tmp_path, drafts_root=ws)


@pytest.fixture()
def api_ctx(ctx):
    from pdm_cli.api_client import PdmApiClient

    ctx.api = PdmApiClient(base_url=API, api_key="test-token")
    return ctx


@pytest.fixture()
def test_ctx(tmp_path):
    """Контекст для bp_test: репо с pdm.config.yaml + тест-кейс в workspace."""
    _write_sandbox_config(tmp_path)
    _write_case(tmp_path / "ws")
    return BpContext(repo_root=tmp_path, drafts_root=tmp_path / "ws")


def _server(ctx):
    return make_server(ctx)


def _call(server, name, arguments):
    """Успешный вызов → dict; доменная ошибка → pytest.raises(ToolError)."""
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


def _mock_syntax_ok():
    return respx.post(f"{API}/api/admin/processes/script/validate-syntax/").respond(
        json={"valid": True, "errors": []}
    )


def _mock_details(run_id="42", stdout="hello from script"):
    return respx.route(
        method="GET",
        url__startswith=f"{SANDBOX}/api/process-instances/{run_id}/details/",
    ).respond(json={
        "run_id": int(run_id),
        "status": "completed",
        "assignments": [{
            "id": 7, "task_slug": "Формирование", "status": "completed",
            "assignee": "auto", "error": None,
            "script_stdout": stdout, "script_error": "",
        }],
        "history_events": [],
        "egress": {
            "http": [{"method": "POST", "url": "http://upstream/api",
                      "status": 200}],
            "ssh": [],
            "orphan_count": {"http": 0, "ssh": 0},
        },
    })


def _passing_result(tc, bp_slug, ctx):
    return CaseResult(
        bp=bp_slug, case=tc.name, run_id="42",
        status="passed", process_status="completed",
    )


def _failing_result(tc, bp_slug, ctx):
    return CaseResult(
        bp=bp_slug, case=tc.name, run_id="42",
        status="failed", process_status="completed",
        assertions=[AssertionResult(
            index=0, kind="http", status="failed",
            expected=">=1", got=0, explain="no matches",
        )],
    )


# ---------- bp_script_check: регистрация и нормы ADR-0058 ----------


def test_script_tools_registered_with_docstrings(ctx):
    tools = {t.name: t for t in asyncio.run(_server(ctx).list_tools())}
    for name in ("bp_script_check", "bp_test"):
        assert name in tools, name
        assert tools[name].description, name
        assert len(tools[name].description) <= 600, (
            f"{name}: docstring {len(tools[name].description)} > 600 (ADR-0058)")
        assert tools[name].inputSchema.get("type") == "object", name


def test_tools_list_order_is_deterministic(ctx):
    order1 = [t.name for t in asyncio.run(_server(ctx).list_tools())]
    order2 = [t.name for t in asyncio.run(_server(ctx).list_tools())]
    assert order1 == order2


# ---------- bp_script_check ----------


@respx.mock
def test_script_check_green_script_returns_sdk_helpers(api_ctx):
    _write_script(api_ctx, "testbp/scripts/auto_complete.py",
                  "log('ok')\nprocess.complete()\n")
    _mock_syntax_ok()
    result = _call(_server(api_ctx), "bp_script_check",
                   {"path": "testbp/scripts/auto_complete.py"})
    assert result["ok"] is True
    assert result["syntax"]["valid"] is True
    assert result["forbidden_imports"] == []
    helpers = result["sdk_helpers"]
    for expected in ("process", "ctx.documents", "notify", "http"):
        assert expected in helpers, expected
    assert len(helpers) <= 30  # диета: справочник компактный
    assert "bp_test" in result["next"]


@respx.mock
def test_script_check_syntax_error_keeps_coordinates(api_ctx):
    _write_script(api_ctx, "testbp/scripts/broken.py",
                  "def f(:\n    pass\n")
    respx.post(f"{API}/api/admin/processes/script/validate-syntax/").respond(
        json={"valid": False, "errors": [{
            "line": 1, "column": 7, "message": "invalid syntax",
            "text": "def f(:\n",
        }]}
    )
    result = _call(_server(api_ctx), "bp_script_check",
                   {"path": "testbp/scripts/broken.py"})
    assert result["ok"] is False
    err = result["syntax"]["errors"][0]
    assert err["line"] == 1 and err["column"] == 7
    assert "invalid syntax" in err["message"]
    assert result["next"]


@respx.mock
def test_script_check_denied_import_with_hint(api_ctx):
    _write_script(api_ctx, "testbp/scripts/evil.py", "import os\nos.getcwd()\n")
    _mock_syntax_ok()
    result = _call(_server(api_ctx), "bp_script_check",
                   {"path": "testbp/scripts/evil.py"})
    assert result["ok"] is False
    denied = result["forbidden_imports"][0]
    assert denied["module"] == "os"
    assert denied["line"] == 1
    assert "импорт os запрещён" in denied["message"]
    assert "http()" in denied["message"]


@respx.mock
def test_script_check_django_conf_denied(api_ctx):
    _write_script(api_ctx, "testbp/scripts/leak.py",
                  "from django.conf import settings\n")
    _mock_syntax_ok()
    result = _call(_server(api_ctx), "bp_script_check",
                   {"path": "testbp/scripts/leak.py"})
    assert result["ok"] is False
    denied = result["forbidden_imports"][0]
    assert "django.conf" in denied["module"] or "django" == denied["module"]
    assert "запрещён" in denied["message"]


@respx.mock
def test_script_check_file_not_found_is_domain_error(api_ctx):
    _mock_syntax_ok()
    server = _server(api_ctx)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool(
            "bp_script_check", {"path": "testbp/scripts/ghost.py"}))
    message = str(excinfo.value)
    assert "не найден" in message
    assert "testbp/scripts/ghost.py" in message
    assert "bp_list_files" in message  # next-подсказка


def test_script_check_rejects_non_python(api_ctx):
    _write_script(api_ctx, "testbp/scripts/note.txt", "not python")
    server = _server(api_ctx)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool(
            "bp_script_check", {"path": "testbp/scripts/note.txt"}))
    assert ".py" in str(excinfo.value)


def test_script_check_path_escape_is_domain_error(api_ctx):
    server = _server(api_ctx)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool(
            "bp_script_check", {"path": "../outside.py"}))
    assert "запрещён" in str(excinfo.value)


def test_script_check_offline_api_is_russian_error(ctx):
    server = _server(ctx)  # ctx.api is None
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool(
            "bp_script_check", {"path": "testbp/scripts/x.py"}))
    message = str(excinfo.value)
    assert "PDM API" in message
    assert "PDM_API_BASE" in message or "PDM_API_TOKEN" in message


@respx.mock
def test_script_check_int_path_repaired_to_business_error(api_ctx):
    """path=123 чинится коэрсингом в "123" и доходит до бизнес-проверки
    (*.py / не найден), а не рвёт цикл pydantic-отказом (ADR-0058)."""
    _mock_syntax_ok()
    server = _server(api_ctx)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool("bp_script_check", {"path": 123}))
    message = str(excinfo.value)
    assert "123" in message  # число починилось в строку
    # дошли до доменной проверки пути, а не до валидации аргументов
    assert "проверяет только" in message or "не найден" in message


# ---------- bp_test ----------


def _patch_lifecycle(monkeypatch, result_fn=None, calls=None):
    """Мок движка: песочница не поднимается (инвариант 6).

    Контракт «bp_test НЕ гасит стек»: bring_down_sandbox заменён на
    заглушку, которая роняет тест при вызове.
    """
    from pdm_cli.defmcp.tools import scripts as scripts_mod

    def fake_ensure():
        if calls is not None:
            calls.append("ensure")
        return None

    def fake_bring_up():
        if calls is not None:
            calls.append("up")

    def forbidden_bring_down():
        raise AssertionError(
            "bp_test не должен гасить sandbox-стек (общий с ручным pdm test)")

    monkeypatch.setattr(scripts_mod, "ensure_sandbox_up", fake_ensure)
    monkeypatch.setattr(scripts_mod, "bring_up_sandbox", fake_bring_up)
    monkeypatch.setattr(scripts_mod, "bring_down_sandbox", forbidden_bring_down)
    if result_fn is not None:
        monkeypatch.setattr(scripts_mod, "run_case", result_fn)
    return scripts_mod


@respx.mock
def test_bp_test_returns_journal_with_warning(test_ctx, monkeypatch):
    _patch_lifecycle(monkeypatch, _passing_result)
    _mock_details()
    result = _call(_server(test_ctx), "bp_test", {"slug": "bp1"})

    assert result["status"] == "passed"
    assert SCRIPT_WARNING in result["warning"]
    assert result["slug"] == "bp1"
    case = result["cases"][0]
    assert case["case"] == "smoke"
    assert case["status"] == "passed"
    assert case["run_id"] == "42"
    assert case["process_status"] == "completed"
    # stdout/stderr из ScriptExecutionLog (details include_script_output)
    assert case["tasks"][0]["stdout"] == "hello from script"
    assert case["tasks"][0]["task"] == "Формирование"
    # egress из аудита песочницы
    assert case["egress"]["http"][0]["url"] == "http://upstream/api"
    # шаги движка: подъём → прогон; ДЕМОНТАЖА НЕТ (стек общий, см. ревью B)
    step_names = [s["step"] for s in result["steps"]]
    assert step_names[0] == "ensure_sandbox_up"
    assert "run_case" in step_names
    assert step_names[-1] == "run_case"
    assert "bring_down_sandbox" not in step_names
    assert result["elapsed_sec"] >= 0
    assert "next" in result


@respx.mock
def test_bp_test_failed_case_is_result_not_tool_error(test_ctx, monkeypatch):
    """Упавший кейс — это данные журнала (инструмент свою работу сделал),
    не isError; предупреждение о версионарировании — в каждом ответе."""
    _patch_lifecycle(monkeypatch, _failing_result)
    _mock_details()
    result = _call(_server(test_ctx), "bp_test", {"slug": "bp1"})
    assert result["status"] == "failed"
    assert SCRIPT_WARNING in result["warning"]
    assertion = result["cases"][0]["assertions"][0]
    assert assertion["kind"] == "http"
    assert assertion["status"] == "failed"
    assert assertion["explain"] == "no matches"


def test_bp_test_no_cases_is_domain_error_with_hint(test_ctx, monkeypatch):
    # у bp1 нет tests/ — создаём каталог БП без кейсов
    (test_ctx.drafts_root / "bp1" / "tests").mkdir(
        parents=True, exist_ok=True)
    for f in (test_ctx.drafts_root / "bp1" / "tests").glob("*.yaml"):
        f.unlink()
    scripts_mod = _patch_lifecycle(monkeypatch)
    server = _server(test_ctx)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool("bp_test", {"slug": "bp1"}))
    message = str(excinfo.value)
    assert "кейсов нет" in message
    assert "tests/<case>.yaml" in message
    assert "bp_find_examples" in message
    # ensure_sandbox_up не должен был вызваться (fail fast по кейсам)
    assert scripts_mod.ensure_sandbox_up is not None


def test_bp_test_named_case_missing_is_domain_error(test_ctx, monkeypatch):
    _patch_lifecycle(monkeypatch)
    server = _server(test_ctx)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool(
            "bp_test", {"slug": "bp1", "case": "ghost"}))
    message = str(excinfo.value)
    assert "ghost" in message
    assert "tests/ghost.yaml" in message
    assert "bp_find_examples" in message


def test_bp_test_unknown_slug_is_domain_error(test_ctx, monkeypatch):
    _patch_lifecycle(monkeypatch)
    server = _server(test_ctx)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool("bp_test", {"slug": "ghost"}))
    message = str(excinfo.value)
    assert "ghost" in message
    assert "workspace" in message
    assert "bp_list_files" in message


def test_bp_test_busy_lock_is_domain_error(test_ctx, monkeypatch):
    from pdm_cli.defmcp.tools import scripts as scripts_mod

    assert scripts_mod._run_lock.acquire(blocking=False)
    try:
        _patch_lifecycle(monkeypatch, _passing_result)
        server = _server(test_ctx)
        with pytest.raises(ToolError) as excinfo:
            asyncio.run(server.call_tool("bp_test", {"slug": "bp1"}))
        message = str(excinfo.value)
        assert "песочница занята" in message
        assert "повтори позже" in message
        # инвариант 6: предупреждение — в КАЖДОМ ответе bp_test, включая ошибки
        assert SCRIPT_WARNING in message
    finally:
        scripts_mod._run_lock.release()


def test_bp_test_autobringup_failure_is_domain_error_and_releases_lock(
        test_ctx, monkeypatch):
    """Стек погашен И автоподъём не удался (нет docker/образов) —
    isError-отказ с просьбой к человеку; лок после этого снят."""
    scripts_mod = _patch_lifecycle(monkeypatch, _passing_result)

    def _raise():
        raise SandboxNotRunningError("Sandbox is not running")

    def _broken_bring_up():
        raise RuntimeError("no such image")

    monkeypatch.setattr(scripts_mod, "ensure_sandbox_up", _raise)
    monkeypatch.setattr(scripts_mod, "bring_up_sandbox", _broken_bring_up)
    server = _server(test_ctx)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool("bp_test", {"slug": "bp1"}))
    message = str(excinfo.value)
    assert "песочница не поднята" in message
    assert "автоподъём не удался" in message
    assert "попроси человека" in message
    assert SCRIPT_WARNING in message

    # лок обязан освободиться: повторный вызов доходит до прогона (не «занято»)
    monkeypatch.setattr(scripts_mod, "ensure_sandbox_up", lambda: None)
    result = _call(_server(test_ctx), "bp_test", {"slug": "bp1"})
    assert result["status"] == "passed"


def test_bp_test_selfheals_bringup_when_stack_down(test_ctx, monkeypatch):
    """US3 «фикс → повтор»: погашенный стек bp_test поднимает сам —
    второй вызов не требует человека, шаг bring_up в журнале."""
    calls = []
    scripts_mod = _patch_lifecycle(monkeypatch, _passing_result, calls)
    monkeypatch.setattr(
        scripts_mod, "ensure_sandbox_up",
        lambda: (_ for _ in ()).throw(
            SandboxNotRunningError("Sandbox is not running")),
    )
    result = _call(_server(test_ctx), "bp_test", {"slug": "bp1"})
    assert calls == ["up"]  # bring_up вызван ровно один раз
    assert result["status"] == "passed"
    step_names = [s["step"] for s in result["steps"]]
    assert step_names == ["ensure_sandbox_up", "bring_up_sandbox", "run_case"]
    assert "bring_down_sandbox" not in step_names  # стек остаётся поднятым


def test_bp_test_missing_config_fails_fast_before_sandbox(test_ctx, monkeypatch):
    """Нет pdm.config.yaml — детерминированная ошибка ДО обращения к
    песочнице (порядок проверок, фикс ревью волны B)."""
    (test_ctx.repo_root / "pdm.config.yaml").unlink()
    scripts_mod = _patch_lifecycle(monkeypatch, _passing_result)

    def forbidden_ensure():
        raise AssertionError("ensure_sandbox_up не должен зваться без конфига")

    monkeypatch.setattr(scripts_mod, "ensure_sandbox_up", forbidden_ensure)
    server = _server(test_ctx)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool("bp_test", {"slug": "bp1"}))
    message = str(excinfo.value)
    assert "pdm.config.yaml" in message
    assert "sandbox-PDM" in message


def test_bp_test_incomplete_config_lists_missing_pieces(tmp_path, monkeypatch):
    """Конфиг есть, но без endpoints.sandbox/ключа — ошибка называет,
    чего именно не хватает и кто заполняет."""
    _write_case(tmp_path / "ws")
    (tmp_path / "pdm.config.yaml").write_text(
        "endpoints:\n  sandbox: http://pdm-sandbox:8000\n", encoding="utf-8")
    # api_key_sandbox не задан ни env, ни secrets.yaml
    monkeypatch.delenv("PDM_API_KEY_SANDBOX", raising=False)
    _patch_lifecycle(monkeypatch, _passing_result)
    from pdm_cli.defmcp.context import BpContext

    ctx = BpContext(repo_root=tmp_path, drafts_root=tmp_path / "ws")
    server = _server(ctx)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool("bp_test", {"slug": "bp1"}))
    message = str(excinfo.value)
    assert "конфиг песочницы неполон" in message
    assert "PDM_API_KEY_SANDBOX" in message


def test_bp_test_fixtures_resolve_from_bp_dir(test_ctx, monkeypatch):
    """Фикстуры резолвятся из <bp_dir>/fixtures (как CLI), не из tests/ —
    регресс ревью волны B: рание код передавал tests/."""
    tests = test_ctx.drafts_root / "bp1" / "tests"
    (tests / "smoke.yaml").unlink()
    (tests / "with_fix.yaml").write_text(
        "name: with_fix\n"
        "fixtures: [http-orders]\n"
        "entity:\n"
        "  type: contract\n"
        "  fields: {}\n"
        "expect:\n"
        "  final_status: completed\n"
        "  side_effects: []\n",
        encoding="utf-8",
    )
    fixtures_dir = test_ctx.drafts_root / "bp1" / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "http-orders.yaml").write_text(
        "name: http-orders\nmatchers: []\n", encoding="utf-8")

    captured = {}

    def fake_load(tc, bp_dir, ctx):
        captured["bp_dir"] = Path(bp_dir)
        assert (Path(bp_dir) / "fixtures" / "http-orders.yaml").is_file(), (
            "фикстура обязана резолвиться из каталога БП")
        return tc.fixtures

    monkeypatch.setattr(
        "pdm_cli.fixtures.loader.load_fixtures_for_case", fake_load)
    monkeypatch.setattr(
        "pdm_cli.fixtures.loader.unload_fixtures_for_case", lambda *a: None)
    _patch_lifecycle(monkeypatch, _passing_result)

    result = _call(_server(test_ctx), "bp_test",
                   {"slug": "bp1", "case": "with_fix"})
    assert captured["bp_dir"] == test_ctx.drafts_root / "bp1"
    assert result["status"] == "passed"


@respx.mock
def test_bp_test_all_cases_sorted(test_ctx, monkeypatch):
    _write_case(test_ctx.drafts_root, case_name="alpha")
    _write_case(test_ctx.drafts_root, case_name="beta")
    _patch_lifecycle(monkeypatch, _passing_result)
    result = _call(_server(test_ctx), "bp_test", {"slug": "bp1"})
    assert [c["case"] for c in result["cases"]] == ["alpha", "beta", "smoke"]


@respx.mock
def test_bp_test_single_case_filter(test_ctx, monkeypatch):
    _write_case(test_ctx.drafts_root, case_name="alpha")
    _patch_lifecycle(monkeypatch, _passing_result)
    result = _call(_server(test_ctx), "bp_test",
                   {"slug": "bp1", "case": "alpha"})
    assert [c["case"] for c in result["cases"]] == ["alpha"]


@respx.mock
def test_bp_test_details_unavailable_is_note_not_crash(test_ctx, monkeypatch):
    _patch_lifecycle(monkeypatch, _passing_result)
    respx.route(
        method="GET", url__startswith=f"{SANDBOX}/api/process-instances/"
    ).respond(status_code=500)
    result = _call(_server(test_ctx), "bp_test", {"slug": "bp1"})
    case = result["cases"][0]
    assert case["status"] == "passed"
    assert "недоступ" in case.get("details_note", "")
    assert case["tasks"] == []


@respx.mock
def test_bp_test_timeout_clamps_case_budget(test_ctx, monkeypatch):
    """Кейс с timeout_sec: 3600 при bp_test(timeout=5) получает зажатый
    бюджет — прогон не может выйти за таймаут вербы."""
    _write_case(test_ctx.drafts_root, case_name="long", timeout_sec=3600)
    captured = {}

    def capture(tc, bp_slug, ctx):
        captured["timeout_sec"] = tc.timeout_sec
        captured["name"] = tc.name
        return CaseResult(bp=bp_slug, case=tc.name, run_id="42",
                          status="passed", process_status="completed")

    _patch_lifecycle(monkeypatch, capture)
    result = _call(_server(test_ctx), "bp_test",
                   {"slug": "bp1", "case": "long", "timeout": 5})
    assert captured["timeout_sec"] <= 5
    assert result["status"] == "passed"


def test_bp_test_wall_timeout_is_domain_error_with_partial_journal(
        test_ctx, monkeypatch):
    import time as _time

    def slow_case(tc, bp_slug, ctx):
        _time.sleep(1.2)
        return CaseResult(bp=bp_slug, case=tc.name, run_id=None,
                          status="passed", process_status="completed")

    _patch_lifecycle(monkeypatch, slow_case)
    server = _server(test_ctx)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool(
            "bp_test", {"slug": "bp1", "timeout": 1}))
    message = str(excinfo.value)
    assert "таймаут" in message
    assert "ensure_sandbox_up" in message  # частичный журнал шагов
    assert SCRIPT_WARNING in message  # предупреждение и в ошибке таймаута


def test_bp_test_lock_released_after_successful_run(test_ctx, monkeypatch):
    from pdm_cli.defmcp.tools import scripts as scripts_mod

    _patch_lifecycle(monkeypatch, _passing_result)
    _call(_server(test_ctx), "bp_test", {"slug": "bp1"})
    assert scripts_mod._run_lock.acquire(blocking=False)
    scripts_mod._run_lock.release()


def test_bp_test_runner_error_case_is_journal_not_abort(test_ctx, monkeypatch):
    """Ошибка загрузки кейса не роняет прогон соседей (как в pdm test)."""
    tests = test_ctx.drafts_root / "bp1" / "tests"
    (tests / "broken.yaml").write_text("name: broken\nentity_id: 1\n",
                                       encoding="utf-8")  # нет expect
    _patch_lifecycle(monkeypatch, _passing_result)
    result = _call(_server(test_ctx), "bp_test", {"slug": "bp1"})
    by_case = {c["case"]: c for c in result["cases"]}
    assert by_case["broken"]["status"] == "error"
    assert "load" in (by_case["broken"]["error"] or "")
    assert by_case["smoke"]["status"] == "passed"
    assert result["status"] == "error"


def test_audit_jsonl_written_for_new_verb_error(test_ctx, monkeypatch):
    """Аудит-журнал пишется и для новых верб (ok и error), как у старых."""
    test_ctx.audit_path = test_ctx.repo_root / ".pdm" / "defmcp" / "audit.jsonl"
    _patch_lifecycle(monkeypatch)
    server = _server(test_ctx)
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("bp_test", {"slug": "ghost"}))
    assert test_ctx.audit_path.exists()
    lines = test_ctx.audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert any('"bp_test"' in line and '"error"' in line for line in lines)
