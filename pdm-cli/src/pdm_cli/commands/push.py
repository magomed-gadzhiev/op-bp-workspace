"""pdm push — ZIP preview/confirm import (транспорт на стенд).

Пакетная форма (processes/<slug>/process.yaml) идёт полным путём:
compile → preview (конфликт-отчёт) → confirm (replace по умолчанию).
Это перенос пакета, не «восстановление git-истины».
Legacy-форма (manifest.yaml) — по-прежнему FSM-lite import_full.
"""

import sys
from pathlib import Path

import click
from rich.console import Console

from ..api_client import PdmApiClient
from ..bpm_package import (
    build_zip,
    diff_packages,
    list_package_slugs,
    parse_package_zip,
    read_package,
    validate_package,
)
from ..config import load_config
from ..repo import list_process_slugs, read_process
from .common import api_options, make_client

console = Console()


def _push_package(client: PdmApiClient, cwd: Path, slug: str, confirm_prod: bool) -> bool:
    """Полный путь: ZIP-пакет → preview → confirm. True — успех."""
    pkg = read_package(cwd, slug)
    errors = validate_package(pkg)
    if errors:
        for e in errors:
            console.print(f"  [red]•[/red] {e}")
        console.print(f"[red]{slug}: пакет не прошёл Tier 0, push отменён[/red]")
        return False

    # ZIP-импорт на сервере ВСЕГДА создаёт новое поколение версий (в _apply_bp
    # нет payload_hash-идемпотентности) — поэтому идентичный пакет не пушим.
    try:
        remote = parse_package_zip(client.export_package(slug))
        if not diff_packages(pkg, remote):
            console.print("  [dim]изменений нет — пропуск (иначе задвоились бы версии)[/dim]")
            return True
    except LookupError:
        pass  # БП на сервере нет — это первая выкладка

    zip_bytes, fname = build_zip(pkg)
    report = client.import_preview(zip_bytes, fname)
    conflicts = (
        report.get("business_process", {}).get("status")
        or report.get("global_effects")
    )
    if conflicts:
        console.print(f"  preview: {str(conflicts)[:200]}")

    result = client.import_confirm(
        zip_bytes, decisions={}, confirm_prod=confirm_prod, filename=fname,
    )
    if result.get("requires_prod_confirmation"):
        console.print(
            f"[red]{slug}: сервер требует подтверждения — "
            f"передай --confirm-prod (справочники будут применены аддитивно)[/red]"
        )
        return False

    updated = len(result.get("updated", []))
    created = len(result.get("created", []))
    subjects = result.get("subjects") or {}
    missing = subjects.get("users_missing") or []
    color = "green" if result.get("success", True) else "red"
    console.print(
        f"  [{color}]→ updated {updated}, created {created}[/{color}]"
    )
    if missing:
        console.print(
            f"  [yellow]⚠ отсутствующие пользователи: "
            f"{[m.get('username') or m for m in missing][:5]}[/yellow]"
        )
    return bool(result.get("success", True))


@click.command("push")
@click.option("--to", "to_env", type=click.Choice(["sandbox", "prod"]),
              default="sandbox", show_default=True)
@click.option("--bp", "bp_slug", default=None,
              help="Push only this BP (default: all).")
@click.option("--confirm-prod", is_flag=True, default=False,
              help="Подтвердить импорт в prod (справочники аддитивно).")
@api_options
@click.pass_context
def push(ctx, to_env, bp_slug, confirm_prod, api_base, api_key):
    """ZIP preview/confirm import of a local YAML package (transport)."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")

    package_slugs = [s for s in list_package_slugs(cwd)
                     if bp_slug is None or s == bp_slug]
    legacy_slugs = [s for s in list_process_slugs(cwd)
                    if s not in package_slugs
                    and (bp_slug is None or s == bp_slug)]

    if not package_slugs and not legacy_slugs:
        console.print("[yellow]No processes found in repo.[/yellow]")
        return

    if to_env == "prod" and legacy_slugs and not confirm_prod:
        console.print(
            "[red]Direct push to prod is not allowed.[/red]\n"
            "Use [cyan]pdm promote <tag>[/cyan] or pass --confirm-prod."
        )
        sys.exit(1)

    pushed = 0
    if package_slugs:
        with make_client(ctx, api_base, api_key) as client:
            for slug in package_slugs:
                console.print(f"  pushing {slug} (package) → {to_env}…")
                if _push_package(client, cwd, slug, confirm_prod=(to_env == "prod" and confirm_prod)):
                    pushed += 1
                else:
                    sys.exit(1)

    if legacy_slugs:
        cfg = load_config(cwd)
        with PdmApiClient(
            base_url=cfg.endpoint(to_env),
            api_key=cfg.api_key(to_env),
            cli_bypass_secret=cfg.cli_bypass_secret,
        ) as client:
            for slug in legacy_slugs:
                console.print(f"  pushing {slug} (legacy R2) → {to_env}…")
                proc = read_process(cwd, slug)
                result = client.import_full(proc)
                console.print(
                    f"    [green]→ version {result.manifest.version} "
                    f"({result.manifest.status})[/green]"
                )
                pushed += 1

    console.print(f"[green]Pushed {pushed} process(es) to {to_env}[/green]")
