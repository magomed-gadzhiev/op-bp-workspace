"""Скриптовый цикл БП: bp_script_check + bp_test (спека 142, волна B).

Обе вербы — новые по ADR-0058: доменные ошибки поднимаются исключениями
(сервер конвертирует их в ToolError → isError=true), а не конвертом
status=error; тексты русские с next-подсказкой. Об источниках:

* DENIED_IMPORTS/SDK_HELPERS — зеркала pdm/backend/processes (sandbox/
  restricted.py DENIED_IMPORTS + guarded_import, script_executor.
  _create_safe_environment). Пакеты развёртываются независимо, поэтому
  логика продублирована (тот же паттерн, что у WeakModelFastMCP).
* bp_test — тонкая обёртка над движком `pdm test` (commands/test_cmd.py):
  конфиг песочницы → ensure_sandbox_up (или автоподъём bring_up_sandbox,
  если стек погашен — цикл US3 «фикс → повтор» не требует человека) →
  load_test_case → fixtures → run_case → run_details (журнал: шаги/
  stdout/stderr/ассерты/egress). Демонтажа НЕТ: bare `compose down`
  гасит общий проект стенда (включая прод-сервисы), а живой стек нужен
  следующей итерации и ручному `pdm test` — гасит его человек.
  Один конкурентный ран (in-process lock), таймаут по умолчанию 300 с.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

# Движок pdm test (тот же, что commands/test_cmd.py): импорты на уровне
# модуля — тесты патчат pdm_cli.defmcp.tools.scripts.<name>, не трогая
# реальную песочницу (инвариант 6). bring_down_sandbox импортируется
# только как патч-цель для контракта «bp_test НЕ гасит стек».
from ...sandbox_lifecycle import (
    SandboxNotRunningError,
    bring_down_sandbox,  # noqa: F401 — см. комментарий выше
    bring_up_sandbox,
    ensure_sandbox_up,
)
from ...test_case import load_test_case
from ...test_runner.runner import RunnerContext, run_case
from ..context import BpContext, workspace_root
from ..guard import GuardError, resolve_under_root

# Зеркало DENIED_IMPORTS из pdm/backend/processes/sandbox/restricted.py.
DENIED_IMPORTS = frozenset({
    "os", "subprocess", "importlib", "socket", "shutil", "ctypes", "pty",
    "multiprocessing", "resource", "signal", "fcntl", "mmap",
})

# django/django.conf запрещены guarded_import отдельно (утечка настроек).
DENIED_DJANGO_CONF = ("django.conf",)

# Справочник SDK-хелперов песочницы скриптов (что доступно в scripts/*.py).
# Порядок фиксированный (детерминированный ответ); кэп для диеты ADR-0058.
SDK_HELPERS: dict[str, str] = {
    "process": "экземпляр процесса (алиас process_instance): .documents, "
               ".catalogs, .assignments(), .complete()",
    "ctx.documents": "API документов: .get(template), .all(), .find(**f), "
                     ".create_document(template, data)",
    "ctx.catalogs": "API справочников: .get(name), .get_items(name, **f)",
    "ctx.assignment": "текущее поручение (или None)",
    "assignment": "текущее поручение (алиас ctx.assignment)",
    "log": "log(*args) — запись в лог выполнения (INFO)",
    "notify_user": "notify_user(user, text, level='info') — in-app уведомление",
    "notify_task": "notify_task(task_name, text) — уведомление исполнителям",
    "notify": "notify(user, text) — устарело, используй notify_user",
    "http": "http(method, url, json=..., secret_ref=...) — HTTP с egress-аудитом",
    "get_secret": "get_secret(name) -> str — именованный секрет",
    "params": "dict — JSON-параметры привязки скрипта",
    "request_input": "request_input(field, prompt, ...) — запрос данных у "
                     "человека (пауза скрипта)",
    "request_form": "request_form(fields, ...) — многострочная форма",
    "once": "once(key, fn) / once.value(key, default) — мемоизация побочных "
            "эффектов",
    "wait_for": "wait_for(event_type, ...) — пауза до события данных",
    "history": "history(**f) -> list[dict] — шаги текущего экземпляра (read-only)",
    "deadline": "deadline(task_name) -> datetime|None — плановый срок задачи",
    "save_report": "save_report(content, filename) — отчёт в MinIO + шаг "
                   "таймлайна",
    "start_process": "start_process(name, context=...) — запуск подпроцесса",
    "assign_task": "assign_task(task_name, user) — назначить задачу",
    "today / now": "today() / now() — текущая дата / дата-время",
    "upload_file / upload_files": "загрузка файлов в MinIO",
    "NegativeDecisionReset": "исключение «отрицательное решение» (сброс "
                             "поручений)",
    # Разрешённая stdlib (импорт доступен): json, datetime, re, math,
    # decimal, pathlib, time, csv, base64, hashlib, uuid, random, string,
    # collections, itertools, functools, operator, timezone,
    # django.utils (НЕ django.conf).
}

DEFAULT_TEST_TIMEOUT_SEC = 300
_LIFECYCLE_RESERVE_SEC = 30  # запас на подъём стека/финальные вызовы журнала
_STDOUT_CAP = 2000
_EGRESS_CAP = 20

# Инвариант спеки 142: предупреждение присутствует в КАЖДОМ ответе bp_test
# (успех, журнал, любая ошибка) — слабая модель не забывает о эффекте.
SCRIPTS_WARNING = "скрипты не версионируются — живые экземпляры исполнят новый код"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_run_lock = threading.Lock()


def _domain(message: str) -> RuntimeError:
    """Доменная ошибка новой вербы: сервер превратит её в isError=true."""
    return RuntimeError(message)


def _test_error(message: str) -> RuntimeError:
    """Доменная ошибка bp_test с обязательным предупреждением."""
    return _domain(f"{message} ({SCRIPTS_WARNING})")


def do_script_check(ctx: BpContext, path: str) -> dict:
    """Проверить workspace/<path> (*.py): синтаксис + запрещённые импорты.

    Синтаксис валидируется PDM API (тот же эндпоинт, что в редакторе
    скриптов админки: line/column/message). Запрещённые импорты —
    denylist песочницы (зеркало restricted.py). Возвращает справочник
    доступных SDK-хелперов — для правки без угадывания.
    """
    if not path or not str(path).strip():
        raise GuardError("пустой путь")
    path = str(path)
    if not path.endswith(".py"):
        raise _domain(
            f"bp_script_check проверяет только *.py — путь от корня "
            f"workspace (получено: {path!r})"
        )
    target = resolve_under_root(workspace_root(ctx), path)
    if ctx.api is None:
        raise _domain(
            "PDM API не настроен (PDM_API_BASE/PDM_API_TOKEN) — "
            "синтаксис-проверка выполняется через сервер"
        )
    if not target.is_file():
        raise FileNotFoundError(
            f"файл {path} не найден в workspace — проверь путь через "
            f"bp_list_files"
        )
    code = target.read_text(encoding="utf-8")

    try:
        syntax = ctx.api.validate_script_syntax(code)
    except Exception as e:  # noqa: BLE001 — транспорт до PDM API
        raise _domain(
            f"синтаксис-проверка через PDM API не удалась: {e} — повтори "
            f"bp_script_check позже; повторится — скажи человеку"
        ) from e
    syntax_errors = [
        {
            "line": e.get("line") or 0,
            "column": e.get("column") or 0,
            "message": e.get("message") or "",
        }
        for e in syntax.get("errors", [])
    ]
    forbidden = _denied_imports(code)

    ok = syntax.get("valid", False) and not forbidden
    return {
        "path": path,
        "ok": ok,
        "syntax": {"valid": syntax.get("valid", False), "errors": syntax_errors},
        "forbidden_imports": forbidden,
        "sdk_helpers": dict(SDK_HELPERS),
        "next": (
            "синтаксис чист — запусти bp_test (кейс tests/<case>.yaml)"
            if ok
            else "исправь файл через bp_edit_file и повтори bp_script_check"
        ),
    }


def _denied_imports(code: str) -> list[dict]:
    """ast-walk по Import/ImportFrom: запрещённые модули с координатами."""
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []  # синтаксис-ошибки уже вернул validate-syntax с координатами
    found: list[dict] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            root = name.split(".")[0]
            if root in DENIED_IMPORTS:
                found.append({
                    "line": getattr(node, "lineno", 0),
                    "column": getattr(node, "col_offset", 0),
                    "module": name,
                    "message": f"импорт {name} запрещён: use http()",
                })
            elif root == "django" and (
                name == "django" or name.startswith(DENIED_DJANGO_CONF)
            ):
                found.append({
                    "line": getattr(node, "lineno", 0),
                    "column": getattr(node, "col_offset", 0),
                    "module": name,
                    "message": "импорт " + name + " запрещён (утечка настроек "
                               "и секретов): используй "
                               "'from django.utils import ...'",
                })
    return found


def _assertion_to_dict(a) -> dict:
    if is_dataclass(a):
        return asdict(a)
    if hasattr(a, "model_dump"):
        return a.model_dump()
    if isinstance(a, dict):
        return a
    return {"repr": repr(a)}


def _engine_step(steps: list[dict], step: str, status: str,
                 detail: str = "") -> None:
    entry = {"step": step, "status": status}
    if detail:
        entry["detail"] = detail
    steps.append(entry)


def do_test(
    ctx: BpContext,
    slug: str,
    case: str | None = None,
    timeout: int = DEFAULT_TEST_TIMEOUT_SEC,
) -> dict:
    """Прогнать тест-кейсы БП движком `pdm test` в песочнице.

    Конфиг песочницы → ensure_sandbox_up (стек погашен — автоподъём
    bring_up_sandbox, цикл «фикс → повтор» не требует человека) → кейсы
    (load → fixtures → run_case → журнал запуска). Без демонтажа: стек
    общий с ручным `pdm test`, гасит его человек. Один конкурентный ран
    (lock), общий таймаут timeout секунд (по умолчанию 300). В каждом
    ответе — предупреждение о версионаровании скриптов.
    """
    if not _SLUG_RE.match(slug or ""):
        raise GuardError(
            f"некорректный slug {slug!r}: ожидается ^[a-z0-9][a-z0-9-]*$"
        )
    bp_dir = workspace_root(ctx) / slug
    if not bp_dir.is_dir():
        raise _test_error(
            f"{slug}/ не найден в workspace — проверь slug через bp_list_files"
        )
    tests_dir = bp_dir / "tests"

    if case is not None:
        case_files = [tests_dir / f"{case}.yaml"]
        if not case_files[0].is_file():
            raise _test_error(
                f"кейс {case} не найден — создай {slug}/tests/"
                f"{case}.yaml в workspace (пример: bp_find_examples)"
            )
    else:
        case_files = sorted(tests_dir.glob("*.yaml")) if tests_dir.is_dir() else []
        if not case_files:
            raise _test_error(
                f"кейсов нет — создай tests/<case>.yaml внутри "
                f"{slug}/ в workspace (пример: bp_find_examples)"
            )

    if not _run_lock.acquire(blocking=False):
        raise _test_error(
            "песочница занята, повтори позже — уже идёт другой прогон bp_test"
        )

    started = time.monotonic()
    steps: list[dict] = []
    cases: list[dict] = []
    status_rank = {"passed": 0, "failed": 1, "timeout": 2, "error": 3}
    try:
        # Конфиг — ДО песочницы: fail fast с точным списком отсутствующего
        # (в контейнере mcp-pdm-bp это первая детерминированная ошибка).
        runner_ctx = _build_runner_context(ctx)

        try:
            ensure_sandbox_up()
            _engine_step(steps, "ensure_sandbox_up", "ok")
        except SandboxNotRunningError as e:
            _engine_step(steps, "ensure_sandbox_up", "error", str(e))
            try:
                bring_up_sandbox()
                _engine_step(steps, "bring_up_sandbox", "ok", "автоподъём")
            except Exception as up_err:  # noqa: BLE001 — подъём = docker/сетап
                _engine_step(steps, "bring_up_sandbox", "error", str(up_err))
                raise _test_error(
                    f"песочница не поднята, автоподъём не удался "
                    f"({up_err}) — попроси человека: docker compose -f "
                    f"docker-compose.full.yml -f tools/pdm-cli/sandbox/"
                    f"docker-compose.sandbox.yml up -d, затем повтори bp_test"
                ) from up_err

        for case_file in case_files:
            case_entry = _run_one_case(
                ctx, slug, bp_dir, case_file, runner_ctx, run_case,
                started, timeout, steps,
            )
            cases.append(case_entry)
            _engine_step(
                steps, "run_case", case_entry["status"],
                f"{case_entry['case']} run_id={case_entry['run_id']}",
            )
    finally:
        # Демонтажа нет (см. docstring модуля): общий `compose down` гасил бы
        # весь проект стенда; стек остаётся для следующей итерации и ручного
        # pdm test. Лок снимаем всегда — «песочница занята» не застревает.
        _run_lock.release()

    elapsed = time.monotonic() - started
    if elapsed > timeout:
        partial = {
            "steps": steps,
            "cases": [
                {"case": c["case"], "status": c["status"]} for c in cases
            ],
        }
        raise _test_error(
            f"таймаут {timeout} с — прогон прерван; журнал до прерывания: "
            f"{json_dumps(partial)}; увеличь timeout или упрости кейс и повтори"
        )

    overall = max(
        (c["status"] for c in cases),
        key=lambda s: status_rank.get(s, 3),
    ) if cases else "error"
    return {
        "slug": slug,
        "status": overall,
        "elapsed_sec": round(elapsed, 1),
        "warning": SCRIPTS_WARNING,
        "steps": steps,
        "cases": cases,
        "next": (
            "тест зелёный — bp_compile, затем bp_draft_save (скрипт "
            "сохраняется в тестовую версию только с зелёным тестом)"
            if overall == "passed"
            else "разбери журнал: исправь скрипт через bp_edit_file → "
                 "bp_script_check → bp_test"
        ),
    }


def _load_runner_config(ctx: BpContext):
    from ...config import ConfigError, load_config

    try:
        return load_config(ctx.repo_root)
    except ConfigError as e:
        raise _test_error(
            f"конфиг песочницы недоступен (pdm.config.yaml): {e} — без него "
            f"bp_test не знает адрес sandbox-PDM"
        ) from e


def _build_runner_context(ctx: BpContext) -> RunnerContext:
    """RunnerContext движка из pdm.config.yaml (как commands/test_cmd).

    Ошибки конфигурации — доменные, с точным списком отсутствующего
    (endpoint/ключ), заполняет человек.
    """
    from ...config import ConfigError

    cfg = _load_runner_config(ctx)
    try:
        return RunnerContext(
            hoverfly_admin=cfg.hoverfly_admin,
            ssh_replay_journal=cfg.ssh_replay_journal,
            sandbox_db_dsn=cfg.sandbox_db_dsn,
            pdm_api_base=cfg.endpoint("sandbox"),
            pdm_api_key=cfg.api_key("sandbox"),
            cli_bypass_secret=cfg.cli_bypass_secret,
            ssh_override_dir=str(ctx.repo_root / ".pdm" / "sandbox"
                                 / "ssh-overrides"),
        )
    except ConfigError as e:
        raise _test_error(
            f"конфиг песочницы неполон: {e} — нужны endpoints.sandbox в "
            f"pdm.config.yaml и ключ PDM_API_KEY_SANDBOX (env) или "
            f".pdm/secrets.yaml:api_key_sandbox; заполняет человек"
        ) from e


def _run_one_case(
    ctx: BpContext,
    slug: str,
    bp_dir: Path,
    case_file: Path,
    runner_ctx,
    run_case_fn,
    started: float,
    timeout: int,
    steps: list[dict],
) -> dict:
    case_name = case_file.stem
    entry: dict = {
        "case": case_name,
        "status": "error",
        "run_id": None,
        "process_status": None,
        "error": "",
        "assertions": [],
        "tasks": [],
        "egress": {"http": [], "ssh": []},
    }
    try:
        tc = load_test_case(case_file)
    except Exception as e:  # noqa: BLE001 — битый кейс не роняет соседей
        entry["error"] = f"load_test_case failed: {e}"
        return entry

    loaded_fixtures: list[str] = []
    try:
        if tc.fixtures:
            from ...fixtures.loader import load_fixtures_for_case

            try:
                # Каталог БП (как commands/test_cmd): резолвер ищет
                # <bp_dir>/fixtures/<stem>.yaml, НЕ <tests>/ (спека 142,
                # фикс ревью волны B).
                loaded_fixtures = load_fixtures_for_case(
                    tc, bp_dir, runner_ctx)
            except RuntimeError as e:
                entry["error"] = f"fixture load failed: {e}"
                return entry

        # Бюджет таймаута: кейс не может выйти за общий лимит вербы.
        budget = timeout - (time.monotonic() - started) - _LIFECYCLE_RESERVE_SEC
        tc_run = tc.model_copy(
            update={"timeout_sec": min(tc.timeout_sec, max(5, int(budget)))}
        )
        result = run_case_fn(tc_run, bp_slug=slug, ctx=runner_ctx)
        entry.update({
            "status": result.status,
            "run_id": result.run_id,
            "process_status": result.process_status,
            "error": result.error or "",
            "assertions": [_assertion_to_dict(a) for a in result.assertions],
        })
        if result.run_id:
            entry = _enrich_with_run_details(ctx, entry, result.run_id)
    finally:
        if loaded_fixtures:
            from ...fixtures.loader import unload_fixtures_for_case

            try:
                unload_fixtures_for_case(loaded_fixtures, runner_ctx)
            except Exception:  # noqa: BLE001 — выгрузка фикстур best-effort
                pass
    return entry


def _enrich_with_run_details(ctx: BpContext, entry: dict, run_id) -> dict:
    """Журнал запуска из sandbox-PDM (details + script stdout/stderr + egress).

    Best-effort: недоступность деталей не роняет результат — в кейс
    пишется заметка, тест/ассерты остаются из движка.
    """
    try:
        cfg = _load_runner_config(ctx)
        from ...api_client import PdmApiClient

        client = PdmApiClient(
            base_url=cfg.endpoint("sandbox"),
            api_key=cfg.api_key("sandbox"),
            cli_bypass_secret=cfg.cli_bypass_secret,
            timeout=30.0,
        )
        try:
            details = client.run_details(run_id, include_script_output=True)
        finally:
            client.close()
    except Exception as e:  # noqa: BLE001 — enrichment не критичен
        entry["details_note"] = f"журнал запуска недоступен: {type(e).__name__}"
        return entry

    entry["tasks"] = [
        {
            "task": a.get("task_slug"),
            "status": a.get("status"),
            "assignee": a.get("assignee"),
            "error": a.get("error"),
            "stdout": (a.get("script_stdout") or "")[:_STDOUT_CAP],
            "stderr": (a.get("script_error") or "")[:_STDOUT_CAP],
        }
        for a in details.get("assignments", [])
    ]
    egress = details.get("egress", {}) or {}
    entry["egress"] = {
        "http": [
            {"method": e.get("method"), "url": e.get("url"),
             "status": e.get("status")}
            for e in (egress.get("http") or [])[:_EGRESS_CAP]
        ],
        "ssh": [
            {"host": e.get("host"), "command": e.get("command"),
             "exit_code": e.get("exit_code")}
            for e in (egress.get("ssh") or [])[:_EGRESS_CAP]
        ],
    }
    return entry


def json_dumps(payload) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, default=str)
