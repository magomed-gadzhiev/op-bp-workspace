"""pdm promote <tag> — push tagged-tree state to prod and publish as the given tag."""

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import click
from click.testing import CliRunner
from rich.console import Console

from ..api_client import PdmApiClient
from ..config import load_config
from ..repo import list_process_slugs, read_process

console = Console()


def _git_tag_exists(cwd: Path, tag: str) -> bool:
    r = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
        cwd=cwd, capture_output=True,
    )
    return r.returncode == 0


def _git_is_dirty(cwd: Path) -> bool:
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=cwd, capture_output=True, text=True,
    )
    return bool(r.stdout.strip())


@contextmanager
def _tag_worktree(repo_root: Path, tag: str):
    """Spin up a temporary git worktree for `tag` and yield its path.

    The worktree is always removed in the finally block, even if an exception
    occurs. The parent dir (.pdm/) is kept; only the worktree entry is cleaned.
    """
    wt_path = repo_root / ".pdm" / f"promote-wt-{tag}"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(wt_path), tag],
        cwd=repo_root, check=True, capture_output=True,
    )
    try:
        yield wt_path
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt_path)],
            cwd=repo_root, capture_output=True,
        )
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=repo_root, capture_output=True,
        )


def _run_promote_gate(cwd: Path, ctx_obj: dict) -> None:
    """Pre-promote gate: validate + last-run.json check.

    Raises click.ClickException if the gate fails. The caller is responsible
    for propagating the exception (i.e. not catching it).
    """
    from .validate import validate

    runner = CliRunner()
    result = runner.invoke(validate, obj=ctx_obj, catch_exceptions=False)
    if result.exit_code != 0:
        raise click.ClickException(
            "pdm validate failed — fix validation errors before promoting.\n"
            + (result.output or "")
        )

    last_run_path = cwd / ".pdm" / "last-run.json"
    if last_run_path.exists():
        try:
            data = json.loads(last_run_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        failed = [
            c for c in data.get("cases", [])
            if c.get("status") in {"failed", "error", "timeout"}
        ]
        if failed:
            names = ", ".join(
                f"{c.get('bp', '?')}/{c.get('case', '?')}" for c in failed[:3]
            )
            suffix = f" (and {len(failed) - 3} more)" if len(failed) > 3 else ""
            raise click.ClickException(
                f"Last test run has failures: {names}{suffix}. "
                "Re-run `pdm test` or use --skip-gate to bypass."
            )


@click.command("promote")
@click.argument("tag")
@click.option(
    "--skip-gate",
    is_flag=True,
    default=False,
    help="Skip pre-promote validation and last-run checks (use with caution).",
)
@click.pass_context
def promote(ctx, tag, skip_gate):
    """Promote the contents of git TAG to a published version in PROD.

    Reads processes from the tagged git tree (via a temporary worktree) so
    that the promoted content matches exactly what was tagged, regardless of
    any uncommitted changes in the working directory.

    Before promoting, runs `pdm validate` and checks .pdm/last-run.json for
    failures. Use --skip-gate to bypass both checks (with a warning).
    """
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    cfg = load_config(cwd)

    if not _git_tag_exists(cwd, tag):
        console.print(f"[red]Git tag '{tag}' does not exist locally.[/red]")
        console.print(f"Create it first: [cyan]git tag {tag}[/cyan]")
        sys.exit(1)

    if _git_is_dirty(cwd):
        console.print(
            "[yellow]Warning: working tree has uncommitted changes. "
            "Promoting from tag snapshot, not from working tree.[/yellow]"
        )

    if skip_gate:
        console.print(
            "[yellow]--skip-gate: skipping pdm validate and last-run check.[/yellow]"
        )
    else:
        _run_promote_gate(cwd, ctx.obj or {})

    with _tag_worktree(cwd, tag) as tag_root:
        slugs = list_process_slugs(tag_root)
        if not slugs:
            console.print("[yellow]No processes found in tag snapshot.[/yellow]")
            return

        with PdmApiClient(
            base_url=cfg.endpoint("prod"),
            api_key=cfg.api_key("prod"),
            cli_bypass_secret=cfg.cli_bypass_secret,
        ) as client:
            for slug in slugs:
                proc = read_process(tag_root, slug)
                console.print(f"  importing {slug}…")
                imported = client.import_full(proc)
                console.print(f"    draft version {imported.manifest.version}")
                console.print(f"  promoting {slug}…")
                published = client.promote(
                    slug, version=imported.manifest.version, tag=tag,
                )
                console.print(
                    f"    [green]→ published version "
                    f"{published.manifest.version}[/green]"
                )

    console.print(f"\n[green]Promoted {len(slugs)} process(es) as {tag}[/green]")
