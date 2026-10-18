"""pdm feedback — feedback management commands (Etap 9 C3)."""

import os
import subprocess
from datetime import datetime, timedelta

import click


@click.group()
def feedback():
    """Feedback management commands."""
    pass


@feedback.command()
@click.option("--older-than", default=90, type=int, help="Delete branches older than N days")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without deleting")
@click.option("--repo-path", default=None, help="Path to feedback repo (default: PDM_FEEDBACK_REPO_LOCAL_PATH env)")
def prune(older_than: int, dry_run: bool, repo_path: str | None):
    """Prune old feedback/auto-* branches from the collector repo."""
    repo_path = repo_path or os.environ.get("PDM_FEEDBACK_REPO_LOCAL_PATH", "/data/feedback-repo")

    if not os.path.isdir(repo_path):
        click.echo(f"Error: repo path does not exist: {repo_path}", err=True)
        raise SystemExit(1)

    prefix = "feedback/auto-"
    cutoff = datetime.now() - timedelta(days=older_than)

    result = subprocess.run(
        ["git", "branch", "--list", f"{prefix}*",
         "--format=%(refname:short) %(creatordate:iso-strict)"],
        cwd=repo_path, capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        click.echo("No matching branches found.")
        return

    deleted = []
    for line in result.stdout.strip().splitlines():
        parts = line.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        branch_name, date_str = parts
        try:
            branch_date = datetime.fromisoformat(date_str.strip())
            if branch_date.replace(tzinfo=None) < cutoff:
                if dry_run:
                    click.echo(f"[dry-run] would delete: {branch_name}")
                    deleted.append(branch_name)
                else:
                    del_result = subprocess.run(
                        ["git", "branch", "-d", branch_name],
                        cwd=repo_path, capture_output=True, text=True,
                    )
                    if del_result.returncode == 0:
                        click.echo(f"deleted: {branch_name}")
                        deleted.append(branch_name)
                    else:
                        click.echo(f"failed to delete: {branch_name} ({del_result.stderr.strip()})", err=True)
        except (ValueError, TypeError):
            continue

    click.echo(f"Total: {len(deleted)} branch(es)")
