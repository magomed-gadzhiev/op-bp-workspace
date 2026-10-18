"""pdm decks — верификационные decks (DRC/MRC правила): git-мастер → PDM.

Волна 1 «Верификация как сервис» (ADR-0012, образец — ADR-0007 для БП):
мастер правил в git (``processes/<slug>/decks/<name>.yaml``), материализация
в БД PDM. Изменение правил — PR, а не правка на экране; ``decks drift``
ловит расхождение в обе стороны.
"""

import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table

from .common import api_options, make_client

console = Console()

# Статус дрейфа → (цвет, маркер, что делать)
DRIFT_HINTS = {
    "in_sync": ("green", "✓", ""),
    "ahead": ("yellow", "→", "git впереди: pdm decks push"),
    "behind": ("red", "←", "БД впереди: бэкпортируйте в git (правка мимо git)"),
    "diverged": ("red", "≠", "одна версия, разное содержимое: поднимите version в git"),
    "missing": ("yellow", "+", "нет в БД: pdm decks push"),
    "orphan": ("red", "∅", "в БД есть, в git нет: удалите или бэкпортируйте"),
}


def read_decks(cwd: Path, bp_slug: str | None = None) -> list[tuple[Path, dict]]:
    """processes/<slug>/decks/*.yaml → [(путь, payload)]."""
    pattern = (
        f"processes/{bp_slug}/decks/*.yaml" if bp_slug else "processes/*/decks/*.yaml"
    )
    out: list[tuple[Path, dict]] = []
    for path in sorted(cwd.glob(pattern)):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("name"):
            out.append((path, data))
        else:
            console.print(f"[red]✗ {path}: ожидался deck-объект с name[/red]")
    return out


def _print_push_result(result: dict) -> None:
    for item in result.get("imported", []):
        console.print(
            f"[green]✓ {item['name']} v{item['version']}[/green] — материализован")
    for item in result.get("unchanged", []):
        console.print(
            f"[dim]• {item['name']} v{item['version']} — без изменений (no-op)[/dim]")
    for item in result.get("conflicts", []):
        console.print(
            f"[red]✗ {item['name']} v{item['version']}: {item['reason']}[/red]")


@click.group("decks")
def decks_group():
    """Верификационные decks (DRC/MRC правила): git — источник истины."""


@decks_group.command("push")
@click.option("--bp", "bp_slug", default=None, help="Только этот процесс (slug); по умолчанию все.")
@click.option("--dry-run", is_flag=True, default=False, help="Preview без записи в БД.")
@click.option("--git-tag", default=None, help="Пометить импорт (коммит/тег).")
@api_options
@click.pass_context
def push(ctx, bp_slug, dry_run, git_tag, api_base, api_key):
    """Загрузить decks из processes/<slug>/decks/ в PDM (идемпотентно)."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    found = read_decks(cwd, bp_slug)
    if not found:
        console.print("[yellow]Deck'ов нет (processes/*/decks/*.yaml).[/yellow]")
        return
    payload = [deck for _, deck in found]
    if git_tag:
        for deck in payload:
            deck.setdefault("git_tag", git_tag)
    with make_client(ctx, api_base, api_key) as client:
        result = client.decks_import(payload, confirm=not dry_run)
    if dry_run:
        console.print("[dim](dry-run: без записи)[/dim]")
    _print_push_result(result)
    if result.get("conflicts"):
        sys.exit(1)


@decks_group.command("drift")
@click.option("--bp", "bp_slug", default=None, help="Только этот процесс (slug).")
@click.option("--json", "as_json", is_flag=True, default=False, help="Машинный вывод.")
@api_options
@click.pass_context
def drift(ctx, bp_slug, as_json, api_base, api_key):
    """Сверить decks в git с БД (детектор дрейфа, exit 1 при расхождении)."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    found = read_decks(cwd, bp_slug)
    if not found:
        console.print("[yellow]Deck'ов нет (processes/*/decks/*.yaml).[/yellow]")
        return
    with make_client(ctx, api_base, api_key) as client:
        report = client.decks_drift([deck for _, deck in found])
    if as_json:
        import json as _json
        click.echo(_json.dumps(report, ensure_ascii=False, indent=1))
    else:
        table = Table(title="Decks drift")
        table.add_column("Статус")
        table.add_column("Deck")
        table.add_column("Детали")
        table.add_column("Действие")
        for status_, items in report.items():
            if status_ == "in_drift" or not isinstance(items, list):
                continue
            color, mark, hint = DRIFT_HINTS.get(status_, ("white", "?", ""))
            for item in items:
                table.add_row(
                    f"[{color}]{mark} {status_}[/{color}]",
                    item.get("name", ""),
                    item.get("detail", ""),
                    hint,
                )
        console.print(table)
    if report.get("in_drift"):
        sys.exit(1)
    console.print("[green]Дрейфа нет: git и БД синхронны.[/green]")
