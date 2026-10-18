"""pdm pull — экспорт ZIP/YAML с сервера в локальный каталог.

Пакетная форма (--bp SLUG): экспортный zip → processes/<slug>/ (полная
фидельность: граф, скрипты, шаблоны, справочники). --zip PATH — офлайн-режим
из уже скачанного пакета («Выгрузить ZIP»). Это выгрузка с сервера,
не «синхронизация git-мастера».
Без --bp — прежний FSM-lite цикл (client-project репо).
"""

import sys
from pathlib import Path

import click
from rich.console import Console

from ..api_client import PdmApiClient
from ..bpm_package import parse_package_zip, write_package
from ..config import load_config
from ..repo import write_process
from .common import api_options, make_client

console = Console()


@click.command("pull")
@click.option("--from", "from_env", type=click.Choice(["prod", "sandbox"]),
              default="prod", show_default=True,
              help="Which environment to pull from.")
@click.option("--bp", "bp_slug", default=None,
              help="Pull only this BP (default: all, legacy FSM-lite form).")
@click.option("--package", "as_package", is_flag=True, default=False,
              help="Пакетная форма: экспортный zip → processes/<slug>/ "
                   "(полная фидельность). Требует --bp или --zip.")
@click.option("--zip", "zip_path", default=None, type=click.Path(exists=True),
              help="Offline: parse this exported zip instead of HTTP (implies --package).")
@click.pass_context
def pull(ctx, from_env, bp_slug, as_package, zip_path):
    """Export ZIP/YAML from the server into processes/<slug>/."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    as_package = as_package or bool(zip_path)

    if as_package:
        if zip_path:
            pkg = parse_package_zip(Path(zip_path).read_bytes())
            if bp_slug and pkg.business_process.slug != bp_slug:
                console.print(
                    f"[red]Слаг пакета {pkg.business_process.slug!r} "
                    f"не совпадает с --bp {bp_slug!r}[/red]"
                )
                sys.exit(1)
        else:
            if not bp_slug:
                console.print("[red]--bp обязателен для пакетного pull[/red]")
                sys.exit(2)
            with make_client(ctx, None, None) as client:
                data = client.export_package(bp_slug)
            pkg = parse_package_zip(data)
        write_package(cwd, pkg)
        console.print(
            f"[green]Pulled package {pkg.business_process.slug} → "
            f"processes/{pkg.business_process.slug}/[/green] "
            f"(задач {len(pkg.business_process.tasks)}, "
            f"шаблонов {len(pkg.document_templates)}, "
            f"справочников {len(pkg.catalogs)})"
        )
        return

    # Legacy: FSM-lite цикл (client-project репо)
    cfg = load_config(cwd)
    with PdmApiClient(
        base_url=cfg.endpoint(from_env),
        api_key=cfg.api_key(from_env),
        cli_bypass_secret=cfg.cli_bypass_secret,
    ) as client:
        if bp_slug:
            slugs = [bp_slug]
        else:
            slugs = [m["slug"] for m in client.list_processes() if m.get("slug")]
        for slug in slugs:
            console.print(f"  pulling {slug} from {from_env}…")
            proc = client.get_full(slug)
            write_process(cwd, proc)

    console.print(f"[green]Pulled {len(slugs)} process(es) from {from_env}[/green]")
