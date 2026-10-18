"""pdm drift — информационное сравнение локального YAML-пакета с экспортом сервера.

Локальный YAML — сборочная форма ZIP; сервер (БД) — рабочее определение.
Команда печатает расхождения и завершается 0, если сравнение удалось.
Ненулевой код — только ошибки чтения, валидации или сети.
"""

import sys
from pathlib import Path

import click
from rich.console import Console

from ..bpm_package import diff_packages, list_package_slugs, parse_package_zip, read_package, validate_package
from .common import api_options, make_client

console = Console()


@click.command("drift")
@click.option("--bp", "bp_slug", default=None,
              help="Только этот БП (по умолчанию все процессы из processes/).")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Машинный вывод: {slug: [строки расхождений]}.")
@api_options
@click.pass_context
def drift(ctx, bp_slug, as_json, api_base, api_key):
    """Сравнить локальный YAML-пакет с экспортом сервера (информационно)."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    if bp_slug and not (cwd / "processes" / bp_slug / "process.yaml").is_file():
        console.print(f"[red]process.yaml не найден: processes/{bp_slug}/[/red]")
        sys.exit(2)

    slugs = [bp_slug] if bp_slug else list_package_slugs(cwd)
    if not slugs:
        console.print("[yellow]Пакетных БП нет (processes/<slug>/process.yaml).[/yellow]")
        return

    report: dict[str, list[str]] = {}
    error_slugs: set[str] = set()
    with make_client(ctx, api_base, api_key) as client:
        for slug in slugs:
            try:
                local = read_package(cwd, slug)
            except Exception as e:
                report[slug] = [f"чтение не удалось: {e}"]
                error_slugs.add(slug)
                continue
            errors = validate_package(local)
            if errors:
                report[slug] = [f"локальная схема невалидна: {e}" for e in errors]
                error_slugs.add(slug)
                continue
            remote = parse_package_zip(client.export_package(slug))
            report[slug] = diff_packages(local, remote)

    drifted = {slug: lines for slug, lines in report.items() if lines}
    if as_json:
        import json as _json
        click.echo(_json.dumps(drifted, ensure_ascii=False, indent=1))
    else:
        for slug, lines in sorted(report.items()):
            if not lines:
                console.print(f"[green]✓ {slug}[/green]: дрейфа нет")
            elif slug in error_slugs:
                console.print(f"[red]✗ {slug}[/red]: {len(lines)} ошибок")
                for line in lines[:40]:
                    console.print(f"    • {line}")
                if len(lines) > 40:
                    console.print(f"    … и ещё {len(lines) - 40}")
            else:
                console.print(f"[cyan]{slug}[/cyan]: {len(lines)} расхождений")
                for line in lines[:40]:
                    console.print(f"    • {line}")
                if len(lines) > 40:
                    console.print(f"    … и ещё {len(lines) - 40}")

    if error_slugs:
        sys.exit(1)
