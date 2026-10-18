"""pdm ws — воркспейс БП для ИИ-контура код-режима (спека 163 §4, ADR-0070).

Рабочий каталог — workspace/<slug>/ (gitignored); состояние минимально,
мастер определения — БД PDM (ADR-0017). Цикл менеджера:
``ws init → правки → ws check → ws test → ws report → «Применить» в PDM UI``.
Применение testing-версии — всегда человек (promote через CLI/PAT запрещён —
серверный инвариант), CLI только готовит отчёт и чек-лист.
"""

from __future__ import annotations

import difflib
import json
import sys
import time
from pathlib import Path

import click
import httpx
from rich.console import Console

from ..bpm_package import (
    build_zip,
    list_package_slugs,
    parse_package_zip,
    read_package,
    validate_package,
    write_package,
)
from ..test_runner.runner import TERMINAL_STATUSES
from .common import api_options, make_client
from .compile import tier0_check

console = Console()

POLL_INTERVAL_SEC = 2.0


def ws_root(cwd: Path) -> Path:
    """Корень воркспейса БП: <cwd>/workspace/<slug>/ (спека 163 §4)."""
    return cwd / "workspace"


def _bp_admin_error(slug: str) -> None:
    console.print(
        f"[red]нет прав администратора этого БП ({slug}): сервер ответил 403.[/red]\n"
        "export/draft-import доступен суперюзеру и администраторам ЭТОГО БП "
        "(спека 163 §1). Попроси владельца БП добавить тебя в admin_users."
    )


def _server_error(e: httpx.HTTPStatusError) -> str:
    """Человекочитаемое тело ошибки сервера (detail/error первыми)."""
    try:
        data = e.response.json()
    except Exception:
        return f"HTTP {e.response.status_code}"
    if isinstance(data, dict):
        for key in ("detail", "error"):
            if data.get(key):
                return f"HTTP {e.response.status_code}: {data[key]}"
    return f"HTTP {e.response.status_code}: {e.response.text[:200]}"


def _ensure_gitignore(ws: Path) -> None:
    """Данные определений БП не версионируются (спека 163 §4/§5.3)."""
    gi = ws / ".gitignore"
    if not gi.is_file():
        ws.mkdir(parents=True, exist_ok=True)
        gi.write_text(
            "# Определения БП не версионируются: мастер — БД PDM (ADR-0017)\n*\n",
            encoding="utf-8",
        )


def _warning_line(w) -> str:
    """Строка предупреждения общих ресурсов ({kind, name, reason}-форма)."""
    if isinstance(w, dict):
        return f"{w.get('kind') or '?'} {w.get('name') or ''}: {w.get('reason') or ''}".strip()
    return str(w)


def _print_diff_summary(diff: dict) -> None:
    """Diff-сводка testing vs действующее (формат draft_diff_summary)."""
    if not diff:
        return
    task_diff = diff.get("task_diff") or {}
    added = task_diff.get("added") or []
    removed = task_diff.get("removed") or []
    changed = task_diff.get("changed") or []
    if not (added or removed or changed):
        console.print("  diff: задачи без изменений")
    if added:
        console.print(f"  [green]+ задачи[/green]: {', '.join(added)}")
    if removed:
        console.print(f"  [red]− задачи[/red]: {', '.join(removed)}")
    for c in changed:
        console.print(
            f"  [yellow]~ задача[/yellow] {c.get('name')}: "
            f"{', '.join(c.get('fields') or [])}"
        )
    bp_diff = diff.get("bp_diff") or []
    if bp_diff:
        console.print(f"  поля БП: {', '.join(map(str, bp_diff))}")
    staged = diff.get("staged_resources") or []
    if staged:
        console.print(f"  стейдж общих ресурсов: {len(staged)} записей")
    warnings = diff.get("warnings") or []
    if warnings:
        console.print(f"  [yellow]⚠ общие ресурсы ({len(warnings)}):[/yellow]")
        for w in warnings:
            console.print(f"    [yellow]•[/yellow] {_warning_line(w)}")
    impact = diff.get("live_impact")
    if impact is not None:
        console.print(
            f"  live_impact: за действующей версией №{impact.get('version_number')} — "
            f"экземпляров {impact.get('instances')}, поручений {impact.get('assignments')}"
        )
    else:
        console.print("  live_impact: действующей published-версии нет")
    nxt = diff.get("next_version_number")
    if nxt:
        console.print(f"  при «Применить» станет версией №{nxt}")


def _read_input_json(path: str | None) -> dict:
    """--input-json: JSON-объект, мерджится в тело POST /api/process-instances/."""
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        console.print(f"[red]--input-json не читается: {e}[/red]")
        sys.exit(2)
    if not isinstance(data, dict):
        console.print("[red]--input-json: ожидается JSON-объект[/red]")
        sys.exit(2)
    return data


@click.group("ws")
def ws():
    """Воркспейс БП: init/check/test/report (спека 163, ADR-0070).

    Рабочий каталог — workspace/<slug>/; применение тестовой версии —
    всегда человек в PDM UI.
    """


@ws.command("init")
@click.argument("slug")
@api_options
@click.pass_context
def ws_init(ctx, slug, api_base, api_key):
    """Экспорт ZIP БП SLUG → workspace/SLUG/ (офлайн-правки)."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    with make_client(ctx, api_base, api_key) as client:
        try:
            data = client.export_package(slug)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                _bp_admin_error(slug)
            else:
                console.print(f"[red]export не удался: {_server_error(e)}[/red]")
            sys.exit(1)
        except httpx.HTTPError as e:
            console.print(f"[red]export не удался: {e}[/red]")
            sys.exit(1)
    pkg = parse_package_zip(data)
    root = ws_root(cwd)
    write_package(cwd, pkg, definitions_root=root)
    # Снапшот последнего импорта — база для `pdm ws diff`
    # (дрилл 2026-10-18); .gitignore воркспейса («*») его не коммитит.
    write_package(cwd, pkg, definitions_root=root / ".ws-origin")
    _ensure_gitignore(root)
    bp = pkg.business_process
    console.print(
        f"[green]ws init: {slug} → workspace/{slug}/[/green] "
        f"(задач {len(bp.tasks)}, скриптов {len(bp.scripts)}, "
        f"шаблонов {len(pkg.document_templates)}, "
        f"справочников {len(pkg.catalogs)})"
    )
    console.print(
        "Дальше: правь YAML → [cyan]pdm ws check[/cyan] → "
        f"[cyan]pdm ws test {slug}[/cyan]"
    )


@ws.command("check")
@click.argument("slug", required=False)
@click.pass_context
def ws_check(ctx, slug):
    """Офлайн Tier 0 по workspace/ (тот же код, что pdm compile)."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    root = ws_root(cwd)
    slugs = [slug] if slug else list_package_slugs(cwd, definitions_root=root)

    if slug and not (root / slug / "process.yaml").is_file():
        console.print(
            f"[red]process.yaml не найден: workspace/{slug}/ "
            f"— сначала pdm ws init {slug}[/red]"
        )
        sys.exit(2)
    if not slugs:
        console.print(
            "[yellow]Workspace пуст (workspace/<slug>/process.yaml) — "
            "сначала pdm ws init <slug>.[/yellow]"
        )
        return
    if tier0_check(cwd, slugs, definitions_root=root):
        sys.exit(1)


@ws.command("diff")
@click.argument("slug")
@click.pass_context
def ws_diff(ctx, slug):
    """Локальный diff workspace/SLUG/ против последнего импорта.

    База — снапшот .ws-origin (обновляется на ws init и на каждый
    успешный draft-import): видно ровно то, что уйдёт в следующий
    draft-import, до его запуска.
    """
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    root = ws_root(cwd)
    cur, origin = root / slug, root / ".ws-origin" / slug
    if not (cur / "process.yaml").is_file():
        console.print(
            f"[red]workspace/{slug}/process.yaml не найден — "
            f"сначала pdm ws init {slug}[/red]"
        )
        sys.exit(2)
    if not origin.is_dir():
        console.print(
            "[yellow]Снапшота .ws-origin нет (воркспейс собран старой "
            f"сборкой CLI) — сделай pdm ws init {slug} заново.[/yellow]"
        )
        sys.exit(2)
    changed = 0
    for path in sorted(cur.rglob("*")):
        if not path.is_file() or path.suffix not in {".yaml", ".py", ".json"}:
            continue
        rel = path.relative_to(cur)
        opath = origin / rel
        cur_lines = path.read_text(encoding="utf-8").splitlines()
        org_lines = (
            opath.read_text(encoding="utf-8").splitlines()
            if opath.is_file() else []
        )
        if cur_lines == org_lines:
            continue
        changed += 1
        diff = difflib.unified_diff(
            org_lines, cur_lines,
            fromfile=f".ws-origin/{slug}/{rel}",
            tofile=f"workspace/{slug}/{rel}", lineterm="",
        )
        for line in diff:
            if line.startswith("+") and not line.startswith("+++"):
                console.print(f"[green]{line}[/green]")
            elif line.startswith("-") and not line.startswith("---"):
                console.print(f"[red]{line}[/red]")
            else:
                console.print(line)
    if changed:
        console.print(f"[bold]ws diff: изменённых файлов {changed}[/bold]")
    else:
        console.print(
            "[green]ws diff: изменений относительно последнего импорта нет[/green]"
        )


@ws.command("test")
@click.argument("slug")
@click.option("--input-json", "input_json", default=None, type=click.Path(exists=True),
              help="JSON-файл с телом старта прогона (name/primary_entity_id/…); "
                   "мерджится в POST /api/process-instances/.")
@click.option("--no-run", is_flag=True, default=False,
              help="Только draft-import (testing-версия), без тестового прогона.")
@click.option("--wait-sec", default=600, show_default=True, type=int,
              help="Таймаут поллинга тестового прогона, сек.")
@api_options
@click.pass_context
def ws_test(ctx, slug, input_json, no_run, wait_sec, api_base, api_key):
    """Сборка ZIP → draft-import → (опц.) тестовый прогон БП SLUG."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    root = ws_root(cwd)
    if not (root / slug / "process.yaml").is_file():
        console.print(
            f"[red]workspace/{slug}/process.yaml не найден — "
            f"сначала pdm ws init {slug}[/red]"
        )
        sys.exit(2)

    pkg = read_package(cwd, slug, definitions_root=root)
    errors = validate_package(pkg)
    if errors:
        for e in errors:
            console.print(f"  [red]•[/red] {e}")
        console.print(f"[red]{slug}: пакет не прошёл Tier 0, draft-import отменён[/red]")
        sys.exit(1)
    zip_bytes, fname = build_zip(pkg)

    with make_client(ctx, api_base, api_key) as client:
        try:
            result = client.draft_import(slug, zip_bytes, fname)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                _bp_admin_error(slug)
            else:
                console.print(f"[red]draft-import не удался: {_server_error(e)}[/red]")
            sys.exit(1)
        except httpx.HTTPError as e:
            console.print(f"[red]draft-import не удался: {e}[/red]")
            sys.exit(1)

        if result.get("error") == "draft_validation_failed":
            console.print("[red]Сервер отклонил пакет (422 draft_validation_failed):[/red]")
            for err in result.get("errors") or []:
                console.print(f"  [red]•[/red] {_warning_line(err)}")
            sys.exit(1)

        version_number = result.get("version")
        if result.get("status") == "idempotent":
            # Идемпотентность payload_hash — серверная (СЦ-Д7): CLI честно
            # отражает no-op, не маскирует его под новую версию.
            console.print(
                f"[yellow]no-op[/yellow]: идентичный payload_hash — сервер оставил "
                f"существующую testing-версию №{version_number} "
                "(без discard и авто-отмены прогонов)"
            )
            console.print(
                "  [dim]подсказка: правки только тел документов/каталогов "
                "учитываются хэшем начиная с текущей сборки сервера; для "
                "testing-версий, созданных раньше, внесите семантическую "
                "правку определения (описание/задача/скрипт)[/dim]"
            )
        else:
            line = f"draft-import: testing-версия №{version_number} ({result.get('status')})"
            replaced = result.get("replaced")
            if replaced:
                line += (
                    f"; прежняя testing №{replaced.get('previous_version')} — в архив"
                )
                cancelled = replaced.get("auto_cancelled_instances")
                if cancelled:
                    line += f", её живые прогоны авто-отменены ({cancelled})"
            console.print(f"[green]{line}[/green]")
        # Снапшот для `ws diff` — этот импорт (дрилл 2026-10-18): diff
        # показывает изменения относительно последнего сохранения на сервер.
        write_package(cwd, pkg, definitions_root=root / ".ws-origin")
        if result.get("users_missing"):
            console.print(
                f"  [yellow]⚠ отсутствующие пользователи: "
                f"{result['users_missing'][:5]}[/yellow]"
            )
        _print_diff_summary(result.get("diff") or {})

        if no_run:
            return

        _start_test_run(client, slug, _read_input_json(input_json), wait_sec)


def _start_test_run(client, slug: str, extra_payload: dict, wait_sec: int) -> None:
    """Тестовый прогон: POST /api/process-instances/ → поллинг до терминального.

    source_version — PK testing-версии (шов W5 принимает PK, не номер;
    /versions/ отдаёт его в testing.id). is_test_run выставляет сервер.
    """
    try:
        registry = client.bp_versions(slug)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]/versions/ не удался: {_server_error(e)}[/red]")
        sys.exit(1)
    testing = registry.get("testing")
    if not testing:
        console.print(
            "[red]Сервер не вернул testing-версию — прогон не на чем запускать.[/red]"
        )
        sys.exit(1)
    bp_pk = (registry.get("process") or {}).get("id")
    payload = {"business_process": bp_pk, "source_version": testing["id"]}
    payload.update(extra_payload)
    console.print(
        f"Тестовый прогон: POST /api/process-instances/ "
        f"(business_process={bp_pk}, source_version={testing['id']} "
        f"= testing №{testing.get('number')}"
        f"{', вход: ' + ', '.join(sorted(extra_payload)) if extra_payload else ''})"
    )
    try:
        run = client.create_process_instance(payload)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            _bp_admin_error(slug)
        else:
            console.print(f"[red]старт прогона не удался: {_server_error(e)}[/red]")
        sys.exit(1)
    except httpx.HTTPError as e:
        console.print(f"[red]старт прогона не удался: {e}[/red]")
        sys.exit(1)

    run_id = run.get("id")
    console.print(f"Прогон #{run_id} запущен, жду терминальный статус (≤{wait_sec} с)…")
    deadline = time.monotonic() + wait_sec
    while True:
        try:
            details = client.run_details(run_id)
        except httpx.HTTPStatusError as e:
            console.print(f"[red]поллинг не удался: {_server_error(e)}[/red]")
            sys.exit(1)
        except httpx.HTTPError as e:
            console.print(f"[red]поллинг не удался: {e}[/red]")
            sys.exit(1)
        status = details.get("status")
        if status in TERMINAL_STATUSES:
            break
        if time.monotonic() >= deadline:
            console.print(
                f"[red]таймаут ожидания ({wait_sec} с): прогон #{run_id} всё ещё "
                f"'{status}' — смотри его в PDM UI; авто-отмены нет.[/red]"
            )
            sys.exit(1)
        time.sleep(POLL_INTERVAL_SEC)

    color = {"completed": "green", "suspended": "yellow"}.get(status, "red")
    console.print(
        f"Прогон #{run_id}: [{color}]{status}[/{color}] "
        f"(завершён: {details.get('completed_at') or '—'})"
    )
    for a in details.get("assignments") or []:
        line = (
            f"  • {a.get('task_slug') or a.get('id')} — {a.get('status')} "
            f"({a.get('assignee') or 'auto'}"
            + (f", {a.get('duration_ms')} мс" if a.get("duration_ms") else "") + ")"
        )
        if a.get("error"):
            console.print(f"[red]{line}\n    ошибка: {a['error']}[/red]")
        else:
            console.print(line)


@ws.command("report")
@click.argument("slug")
@api_options
@click.pass_context
def ws_report(ctx, slug, api_base, api_key):
    """Человекочитаемый отчёт по версиям БП SLUG + чек-лист применения."""
    with make_client(ctx, api_base, api_key) as client:
        try:
            registry = client.bp_versions(slug)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                _bp_admin_error(slug)
            else:
                console.print(f"[red]/versions/ не удался: {_server_error(e)}[/red]")
            sys.exit(1)
        except httpx.HTTPError as e:
            console.print(f"[red]/versions/ не удался: {e}[/red]")
            sys.exit(1)

    process = registry.get("process") or {}
    console.print(f"[bold]Отчёт по БП {slug}[/bold] "
                  f"({process.get('name') or '—'}, pk={process.get('id') or '—'})")
    for v in registry.get("versions") or []:
        marker = ""
        if v.get("status") == "testing":
            marker = " ← testing"
        elif v.get("status") == "published":
            marker = " ← действующая"
        console.print(f"  версия №{v.get('number')} — {v.get('status')}{marker}")

    testing = registry.get("testing")
    published = registry.get("published")
    if not testing:
        console.print("[yellow]Testing-версии нет — применять нечего.[/yellow]")
        console.print("Цикл: pdm ws init → правки → pdm ws check → pdm ws test.")
        return
    if published:
        console.print(f"Действующая (published) версия: №{published.get('number')}")

    diff = registry.get("diff") or {}
    if diff:
        console.print("[bold]Diff-сводка testing vs действующее:[/bold]")
        _print_diff_summary(diff)

    console.print("[bold]Чек-лист применения (в PDM UI, человеком):[/bold]")
    console.print(f"  1. Открой БП «{process.get('name') or slug}» в админке PDM.")
    console.print(f"  2. Вкладка версий → testing-версия №{testing.get('number')}; "
                  "сверь diff-сводку и live_impact выше.")
    console.print("  3. Если всё ок — нажми «Применить» (testing → published).")
    console.print("  4. Прежняя published уйдёт в архив автоматически; "
                  "живые тест-прогоны этой версии будут авто-отменены.")
    console.print("  Применение через CLI/PAT невозможно — только человек "
                  "(серверный инвариант, спека 163 §2.4).")
