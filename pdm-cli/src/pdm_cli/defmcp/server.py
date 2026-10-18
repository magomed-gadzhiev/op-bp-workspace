"""Сборка FastMCP-сервера defmcp (спека 070).

Каждый инструмент — явная типизированная функция (схему FastMCP строит из
сигнатуры), вызов идёт через _call: аудит JSONL + ошибки как dict со
status=error (агенту читаемее, чем исключение транспорта).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .context import BpContext


def build_context(repo_root: Path) -> BpContext:
    """Контекст из окружения: MCP_BP_DRAFTS_ROOT, PDM_API_BASE/PDM_API_TOKEN."""
    from ..api_client import PdmApiClient

    api = None
    base = os.environ.get("PDM_API_BASE")
    key = os.environ.get("PDM_API_TOKEN")
    if base and key:
        api = PdmApiClient(base_url=base, api_key=key, timeout=120.0)
    drafts_env = os.environ.get("MCP_BP_DRAFTS_ROOT")
    return BpContext(
        repo_root=repo_root,
        api=api,
        drafts_root=Path(drafts_env) if drafts_env else None,
        audit_path=repo_root / ".pdm" / "defmcp" / "audit.jsonl",
    )


def _audit(
    ctx: BpContext,
    tool: str,
    args: dict,
    status: str,
    duration_ms: int,
    error: str | None = None,
) -> None:
    if ctx.audit_path is None:
        return
    try:
        ctx.audit_path.parent.mkdir(parents=True, exist_ok=True)
        # content длинный и не нужен в журнале — режем до 300 символов
        safe_args = {
            k: (v[:300] + "…" if isinstance(v, str) and len(v) > 300 else v)
            for k, v in args.items()
        }
        with ctx.audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(
                {
                    "tool": tool,
                    "args": safe_args,
                    "status": status,
                    "duration_ms": duration_ms,
                    "error": error,
                },
                ensure_ascii=False,
                default=str,
            ) + "\n")
    except OSError:
        pass  # аудит не должен ронять инструмент


def _call(ctx: BpContext, name: str, fn, **kwargs) -> dict:
    start = time.monotonic()
    try:
        result = fn(ctx, **kwargs)
        _audit(ctx, name, kwargs, "ok",
               int((time.monotonic() - start) * 1000))
        return result
    except Exception as e:  # noqa: BLE001 — граница транспорта
        error = f"{type(e).__name__}: {e}"
        _audit(ctx, name, kwargs, "error",
               int((time.monotonic() - start) * 1000), error)
        return {"status": "error", "error": error}


def _call_strict(ctx: BpContext, name: str, fn, **kwargs) -> dict:
    """Вызов новых верб (ADR-0058 п.2): доменные ошибки — ToolError.

    В отличие от _call (конверт status=error, isError=false), новые вербы
    поднимают ToolError — протокольный слой отдаёт её с isError=true,
    слабая модель не трактует отказ как успех. Аудит JSONL тот же.
    """
    from mcp.server.fastmcp.exceptions import ToolError

    start = time.monotonic()
    try:
        result = fn(ctx, **kwargs)
        _audit(ctx, name, kwargs, "ok",
               int((time.monotonic() - start) * 1000))
        return result
    except ToolError:
        _audit(ctx, name, kwargs, "error",
               int((time.monotonic() - start) * 1000))
        raise
    except Exception as e:  # noqa: BLE001 — граница транспорта
        error = str(e) or type(e).__name__
        _audit(ctx, name, kwargs, "error",
               int((time.monotonic() - start) * 1000), error)
        raise ToolError(error) from e


def make_server(ctx: BpContext):
    from mcp.server.transport_security import TransportSecuritySettings

    from .tools import drafts, files, process_new, scripts, validate

    # Docker DNS name LibreChat uses as Host (same pattern as mcp-pdm).
    extra_hosts = [
        h.strip()
        for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",")
        if h.strip()
    ]
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"] + extra_hosts,
    )

    # WeakModelFastMCP (как ProfiledFastMCP в pdm/backend/mcp_server, спека
    # 138): коэрсинг «почти правильных» аргументов слабой модели + русская
    # ошибка с подсказкой вместо pydantic-английского.
    from .weak_model import WeakModelFastMCP

    server = WeakModelFastMCP(
        "pdm-bp",
        instructions=(
            "Chat-edit тестовой версии БП (спека 143, ADR-0059: ИИ пишет "
            "только в тестовую версию, публикация — человек в админке PDM). "
            "Цикл: bp_draft_from_server (или bp_new_process) → bp_read_file → "
            "bp_edit_file → bp_compile → bp_draft_save. Git не используется."
        ),
        transport_security=transport_security,
    )

    @server.tool()
    def bp_list_files(slug: str | None = None) -> dict:
        """Дерево файлов workspace черновиков (yaml/py/md/json), пути от
        корня workspace. Без slug — по всем БП; со slug — только этот БП."""
        return _call(ctx, "bp_list_files", files.do_list_files, slug=slug)

    @server.tool()
    def bp_read_file(path: str) -> dict:
        """Прочитать файл определения. Путь относительно корня workspace
        (например 'lem/tasks/03-approval.yaml')."""
        return _call(ctx, "bp_read_file", files.do_read_file, path=path)

    @server.tool()
    def bp_edit_file(
        path: str,
        content: str,
        expected_current: str | None = None,
    ) -> dict:
        """Записать файл определения (путь от корня workspace). YAML
        валидируется до записи. expected_current — содержимое, которое ты
        видел при чтении; если файл с тех пор изменился, будет отказ
        (перечитай)."""
        return _call(
            ctx, "bp_edit_file", files.do_edit_file,
            path=path, content=content, expected_current=expected_current,
        )

    @server.tool()
    def bp_new_process(slug: str, title: str, tasks: list[str] | None = None) -> dict:
        """Создать новый БП в package-форме: process.yaml + tasks/001-*.yaml.
        tasks — названия задач по порядку (по умолчанию одна)."""
        return _call(
            ctx, "bp_new_process", process_new.do_new_process,
            slug=slug, title=title, tasks=tasks,
        )

    @server.tool()
    def bp_compile(slug: str | None = None) -> dict:
        """Tier 0: собрать и провалидировать пакеты БП из workspace (offline,
        без сети). Ошибки пофайлово. Обязателен до bp_draft_save."""
        return _call(ctx, "bp_compile", validate.do_compile, slug=slug)

    @server.tool()
    def bp_draft_from_server(slug: str) -> dict:
        """Что: выгрузить определение БП с сервера в workspace для правок:
        тестовая версия (при наличии), иначе действующая (published).
        Когда: перед правкой существующего БП; повторный вызов перезаливает
        workspace, несохранённые правки теряются."""
        return _call_strict(
            ctx, "bp_draft_from_server", drafts.do_draft_from_server, slug=slug,
        )

    @server.tool()
    def bp_draft_save(slug: str) -> dict:
        """Что: собрать пакет (Tier 0) и сохранить его в тестовую версию БП
        на сервере (замена прежней тестовой). Возвращает номер версии,
        diff-сводку и статус. Когда: правки готовы; подтверждение человека
        НЕ нужно — публикация выполняет человек в админке PDM."""
        return _call_strict(
            ctx, "bp_draft_save", drafts.do_draft_save, slug=slug,
        )

    @server.tool()
    def bp_draft_status(slug: str) -> dict:
        """Что: показать состояние тестовой версии БП: номер, diff с
        действующей, есть ли несохранённые файлы в workspace. Когда: перед
        правками и перед отчётом пользователю."""
        return _call_strict(
            ctx, "bp_draft_status", drafts.do_draft_status, slug=slug,
        )

    @server.tool()
    def bp_script_check(path: str) -> dict:
        """Что: проверить скрипт processes/<path> (*.py) — синтаксис
        (line/column/message через PDM API), запрещённые импорты песочницы
        и список SDK-хелперов. Когда: после каждой правки scripts/*.py, до
        bp_test. Возвращает ok, syntax.errors, forbidden_imports,
        sdk_helpers; чини по координатам и повтори."""
        return _call_strict(
            ctx, "bp_script_check", scripts.do_script_check, path=path,
        )

    @server.tool()
    def bp_test(
        slug: str,
        case: str | None = None,
        timeout: int = 300,
    ) -> dict:
        """Что: прогнать тест-кейс БП в песочнице движком pdm test — журнал:
        шаги, stdout/stderr, ассерты, egress; погашенный стек поднимает сам.
        Когда: скрипт прошёл bp_script_check и есть
        workspace/<slug>/tests/<case>.yaml. Один ран одновременно, таймаут
        timeout сек (по умолчанию 300). Скрипт сохраняется в тестовую
        версию (bp_draft_save) только с зелёным тестом."""
        return _call_strict(
            ctx, "bp_test", scripts.do_test,
            slug=slug, case=case, timeout=timeout,
        )

    return server


def run_server(
    *,
    repo_root: Path,
    transport: str = "http",
    host: str = "127.0.0.1",
    port: int = 8016,
    skip_version_check: bool = False,
) -> None:
    ctx = build_context(repo_root)
    if ctx.api is not None and not skip_version_check:
        from ..mcp.server import ApiVersionMismatch, verify_api_version

        try:
            verify_api_version(ctx.api)
        except ApiVersionMismatch as e:
            raise SystemExit(f"FATAL: {e}")
        except Exception as e:
            raise SystemExit(f"FATAL: PDM API недоступен: {e}")
    elif ctx.api is None:
        print(
            "WARN: PDM_API_BASE/PDM_API_TOKEN не заданы — offline-режим: "
            "работают bp_list/read/edit/new_process/compile; "
            "bp_draft_from_server, bp_draft_save, bp_draft_status и "
            "bp_script_check недоступны; bp_test работает при настроенном "
            "pdm.config.yaml (sandbox)",
            flush=True,
        )

    server = make_server(ctx)
    if transport == "stdio":
        server.run(transport="stdio")
        return
    app = server.streamable_http_app()
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")
