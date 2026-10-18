"""pdm new-bp — scaffold a new business-process skeleton locally.

Deterministic, non-interactive generator: builds a populated `Manifest` + one
placeholder `Task` in memory and serializes them with the shared `write_process`
so the result is byte-stable and passes `pdm validate` with zero manual edits.

This command is the single source of truth for the BP skeleton layout (FR-022);
the `pdm-create-process` skill defers file creation to it rather than hand-writing
the directory structure.
"""

import sys
from pathlib import Path

import click
from rich.console import Console

from ..models import Manifest, Process, Task, _validate_slug
from ..repo import write_process

console = Console()

# Sub-component directories created empty alongside the serialized manifest/tasks.
# (write_process already creates tasks/ — and entities/ scripts/ — from the model.)
_EMPTY_SUBDIRS = ("fixtures", "tests", "decisions")


def _humanize(slug: str) -> str:
    """Default human-readable name from a slug, e.g. 'demo-bp' -> 'Demo Bp'."""
    return slug.replace("-", " ").title()


@click.command("new-bp")
@click.argument("slug")
@click.option("--name", default=None, help="Human-readable manifest name (default: humanized slug).")
@click.option("--description", default="", help="Manifest description (default: empty).")
@click.option(
    "--target-dir",
    type=click.Path(),
    default=None,
    help="Client-project root under which processes/ lives (default: current working directory).",
)
@click.pass_context
def new_bp(ctx, slug, name, description, target_dir):
    """Scaffold processes/<slug>/ with a valid manifest + placeholder task."""
    # 1. Validate the slug before any filesystem access — reject, create nothing (FR-020).
    try:
        _validate_slug(slug)
    except ValueError as exc:
        console.print(f"[red]Invalid slug '{slug}':[/red] {exc}")
        sys.exit(1)

    # 2. Resolve the target root (mirrors sibling commands' ctx.obj['cwd'] convention).
    root = Path(target_dir) if target_dir else Path((ctx.obj or {}).get("cwd") or ".")
    bp_dir = root / "processes" / slug

    # 3. Refuse to overwrite an existing BP — write nothing, exit non-zero (FR-019).
    if (bp_dir / "manifest.yaml").exists():
        console.print(f"[red]Process '{slug}' already exists[/red] at {bp_dir}.")
        console.print(
            "Nothing was written. Use `pdm pull` to refresh or the "
            "pdm-edit-process skill to modify it."
        )
        sys.exit(1)

    # 4. Build the in-memory Process — model construction validates every field (FR-016/FR-017).
    try:
        process = Process(
            manifest=Manifest(
                slug=slug,
                name=name or _humanize(slug),
                description=description or "",
                version=1,
                status="draft",
                owner=None,
            ),
            tasks=[Task(slug="placeholder", title="Placeholder task", kind="script", config={})],
        )
    except Exception as exc:  # pragma: no cover - slug already validated above
        console.print(f"[red]Could not build process '{slug}':[/red] {exc}")
        sys.exit(1)

    # 5. Serialize manifest + tasks/ via the shared writer, then create the empty sub-dirs (FR-018/FR-022).
    write_process(root, process)
    for sub in _EMPTY_SUBDIRS:
        (bp_dir / sub).mkdir(parents=True, exist_ok=True)

    console.print(f"[green]Created[/green] new business process at {bp_dir}")
    console.print(
        f"Next: edit the manifest/tasks, run `pdm validate --bp {slug}`, then commit."
    )
