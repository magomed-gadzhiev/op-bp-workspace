"""pdm compile — Tier 0: собрать и провалидировать локальный YAML-пакет БП.

Компилирует processes/<slug>/ в zip-пакет без похода в сеть: спарс-YAML
нормализуется дефолтами, перекрёстные ссылки (биндинги, условия, шаблоны,
справочники) проверяются машинно. Локальный YAML — сборочная форма ZIP,
не «git-мастер» определения. Первый ярус верификации: ценз готовности
пакета, выполняемый за миллисекунды и ноль токенов.
"""

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ..bpm_package import (
    build_zip,
    list_package_slugs,
    read_package,
    validate_package,
)

console = Console()


def tier0_check(
    cwd: Path,
    slugs: list[str],
    *,
    definitions_root: Path | None = None,
    out_dir: Path | None = None,
) -> int:
    """Общий движок Tier 0 (pdm compile и pdm ws check, спека 163 §4.2):
    чтение + офлайн-валидация пакетов, ноль сети. Возвращает число
    пакетов с ошибками; печать — по одному пакету, итог только на успехе.
    """
    failures = 0
    for slug in slugs:
        try:
            pkg = read_package(cwd, slug, definitions_root=definitions_root)
        except Exception as e:  # pydantic/IO — любая ошибка читается как есть
            console.print(f"[red]{slug}: чтение не удалось: {e}[/red]")
            failures += 1
            continue

        errors = validate_package(pkg)
        bp = pkg.business_process
        status = "[green]ok[/green]" if not errors else "[red]ошибки[/red]"
        console.print(
            f"{status} [bold]{slug}[/bold]: задач {len(bp.tasks)}, "
            f"скриптов {len(bp.scripts)}, шаблонов {len(pkg.document_templates)}, "
            f"справочников {len(pkg.catalogs)}"
        )
        for e in errors:
            console.print(f"  [red]•[/red] {e}")
        failures += 1 if errors else 0

        if out_dir:
            data, fname = build_zip(pkg)
            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / fname).write_bytes(data)
            console.print(f"    → {out / fname} ({len(data)} b)")

    if failures:
        return failures
    summary = Table(show_header=False, box=None)
    summary.add_row(f"Tier 0 пройден: {len(slugs)} БП, ошибок {failures}")
    console.print(summary)
    return failures


@click.command("compile")
@click.option("--bp", "bp_slug", default=None,
              help="Только этот БП (по умолчанию все процессы из processes/).")
@click.option("--out", "out_dir", default=None, type=click.Path(),
              help="Каталог для выгрузки собранных zip (опционально).")
@click.pass_context
def compile_cmd(ctx, bp_slug, out_dir):
    """Собрать и провалидировать локальный YAML-пакет БП (Tier 0)."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    slugs = [bp_slug] if bp_slug else list_package_slugs(cwd)

    if bp_slug and not (cwd / "processes" / bp_slug / "process.yaml").is_file():
        console.print(f"[red]process.yaml не найден: processes/{bp_slug}/[/red]")
        sys.exit(2)
    if not slugs:
        console.print("[yellow]Пакетных БП нет (processes/<slug>/process.yaml).[/yellow]")
        return

    if tier0_check(cwd, slugs, out_dir=Path(out_dir) if out_dir else None):
        sys.exit(1)
