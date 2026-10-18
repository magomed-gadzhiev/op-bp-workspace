"""pdm scaffold — manage client-project scaffold files."""
from pathlib import Path

import click
from rich.console import Console

from ..skills import install_skills

console = Console()


@click.group("scaffold")
def scaffold_group():
    """Manage PDM scaffold files in this client-project."""


@scaffold_group.command("install")
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing skill files with package versions.",
)
@click.option(
    "--target-dir",
    type=click.Path(),
    default=None,
    help="Client-project root (default: current working directory).",
)
@click.pass_context
def install(ctx, force, target_dir):
    """Install or update PDM skill files in .claude/skills/pdm/."""
    cwd = Path(target_dir) if target_dir else Path((ctx.obj or {}).get("cwd") or ".")
    results = install_skills(cwd, force=force)
    if not results:
        console.print("[yellow]Warning: skill templates not found in package.[/yellow]")
        return

    installed = sorted(n for n, a in results.items() if a == "installed")
    overwritten = sorted(n for n, a in results.items() if a == "overwritten")
    skipped = sorted(n for n, a in results.items() if a == "skipped")

    for name in installed:
        console.print(f"[green]Installed:[/green] {name}")
    for name in overwritten:
        console.print(f"[cyan]Overwritten:[/cyan] {name}")
    for name in skipped:
        console.print(f"[dim]Skipped (exists):[/dim] {name}")

    total_changed = len(installed) + len(overwritten)
    if total_changed == 0:
        console.print(f"[green]All skills up to date ({len(skipped)} files).[/green]")
    else:
        console.print(
            f"\nSkills: {len(installed)} installed, "
            f"{len(overwritten)} overwritten, {len(skipped)} skipped."
        )
