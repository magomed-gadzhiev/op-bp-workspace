"""pdm diff — compare local repo state with remote PDM."""

import difflib
import json
from pathlib import Path

import click
import httpx
from rich.console import Console

from ..api_client import PdmApiClient
from ..config import load_config
from ..repo import list_process_slugs, read_process

console = Console()


@click.command("diff")
@click.option("--against", type=click.Choice(["prod", "sandbox"]),
              default="sandbox", show_default=True,
              help="Compare against this environment.")
@click.option("--bp", "bp_slug", default=None,
              help="Diff only this BP (default: all in repo).")
@click.pass_context
def diff(ctx, against, bp_slug):
    """Compare the local repo with the remote PDM state."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    cfg = load_config(cwd)
    slugs = [bp_slug] if bp_slug else list_process_slugs(cwd)

    if not slugs:
        console.print("[yellow]No processes in repo to diff.[/yellow]")
        return

    any_diff = False
    with PdmApiClient(
        base_url=cfg.endpoint(against),
        api_key=cfg.api_key(against),
        cli_bypass_secret=cfg.cli_bypass_secret,
    ) as client:
        for slug in slugs:
            local = read_process(cwd, slug)
            try:
                remote = client.get_full(slug)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    console.print(
                        f"[yellow]{slug}: not present in {against} (404)[/yellow]"
                    )
                    any_diff = True
                    continue
                raise
            local_dump = _normalize(local)
            remote_dump = _normalize(remote)
            if local_dump == remote_dump:
                continue

            any_diff = True
            console.print(f"[cyan]── {slug} ──[/cyan]")
            for line in difflib.unified_diff(
                remote_dump.splitlines(),
                local_dump.splitlines(),
                fromfile=f"{against}:{slug}",
                tofile=f"local:{slug}",
                lineterm="",
            ):
                if line.startswith("+") and not line.startswith("+++"):
                    console.print(f"[green]{line}[/green]")
                elif line.startswith("-") and not line.startswith("---"):
                    console.print(f"[red]{line}[/red]")
                else:
                    console.print(line)

    if not any_diff:
        console.print(f"[green]No differences vs {against}.[/green]")


def _normalize(process) -> str:
    """Stable text representation for diffing — drops version/status (always differ)."""
    data = process.model_dump()
    data["manifest"].pop("version", None)
    data["manifest"].pop("status", None)
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)
