"""pdm validate — schema-check all processes in the repo."""

import re
import sys
from pathlib import Path

import click
from pydantic import ValidationError
from rich.console import Console

from ..repo import list_process_slugs, read_process
from ..fixtures.http import load_http_fixture
from ..fixtures.ssh import load_ssh_fixture
from ..fixtures.versioning import resolve_fixture_file
from ..test_case import load_test_case

console = Console()


def _check_fixture_refs(repo_root: Path, slug: str, errors: list[str]) -> None:
    """Verify every fixture reference in a BP's test cases resolves (E16 FR-007/C-V12).

    Bare refs to existing active files and legacy fixtures resolve cleanly (no new
    error — SC-002). A pinned ``@N`` with no such version, or a bare ref to a missing
    active file, is reported. Test-case schema problems are out of scope here and are
    skipped silently to stay regression-free.
    """
    tests_dir = repo_root / "processes" / slug / "tests"
    if not tests_dir.is_dir():
        return
    bp_dir = repo_root / "processes" / slug
    for path in sorted(tests_dir.glob("*.yaml")):
        rel = f"processes/{slug}/tests/{path.name}"
        try:
            tc = load_test_case(path)
        except Exception:
            continue  # test-case schema validation is not this check's concern
        for ref in tc.fixtures:
            try:
                resolve_fixture_file(bp_dir, ref)
            except FileNotFoundError as e:
                errors.append(f"{rel}: fixture ref '{ref}' — {e}")


SUSPICIOUS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9._\-]{10,}"), "looks like a Bearer token"),
    (re.compile(r"\b[a-fA-F0-9]{32,}\b"), "looks like a hex secret/hash"),
]


def _check_fixtures(repo_root: Path, errors: list[str], warnings: list[str]) -> None:
    for f in repo_root.glob("processes/*/fixtures/http-*.yaml"):
        try:
            load_http_fixture(f)
        except Exception as e:
            errors.append(f"{f}: {e}")
            continue
        text = f.read_text(encoding="utf-8")
        for pat, why in SUSPICIOUS:
            if pat.search(text):
                warnings.append(f"{f}: PII suspect — {why}")
    for f in repo_root.glob("processes/*/fixtures/ssh-*.yaml"):
        try:
            load_ssh_fixture(f)
        except Exception as e:
            errors.append(f"{f}: {e}")
            continue
        text = f.read_text(encoding="utf-8")
        for pat, why in SUSPICIOUS:
            if pat.search(text):
                warnings.append(f"{f}: PII suspect — {why}")

    # E16 FR-023: archived versions get the same parse-load + PII scan as active files.
    for f in repo_root.glob("processes/*/fixtures/_archive/*/v*.yaml"):
        stem = f.parent.name
        loader = load_http_fixture if stem.startswith("http-") else (
            load_ssh_fixture if stem.startswith("ssh-") else None
        )
        if loader is None:
            continue
        try:
            loader(f)
        except Exception as e:
            errors.append(f"{f}: {e}")
            continue
        text = f.read_text(encoding="utf-8")
        for pat, why in SUSPICIOUS:
            if pat.search(text):
                warnings.append(f"{f}: PII suspect — {why}")


@click.command("validate")
@click.option("--bp", "bp_slug", default=None, help="Validate only this BP.")
@click.pass_context
def validate(ctx, bp_slug):
    """Validate the structure of all processes in the repo."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    slugs = [bp_slug] if bp_slug else list_process_slugs(cwd)

    if not slugs:
        console.print("[yellow]No processes found in repo.[/yellow]")
        return

    errors: list[tuple[str, str]] = []
    for slug in slugs:
        try:
            read_process(cwd, slug)
        except ValidationError as e:
            errors.append((slug, str(e)))
        except FileNotFoundError as e:
            errors.append((slug, str(e)))

    fixture_errors: list[str] = []
    fixture_warnings: list[str] = []
    _check_fixtures(cwd, fixture_errors, fixture_warnings)

    for slug in slugs:
        _check_fixture_refs(cwd, slug, fixture_errors)

    if fixture_warnings:
        for w in fixture_warnings:
            console.print(f"[yellow]⚠ WARNING: {w}[/yellow]")

    if fixture_errors:
        for fe in fixture_errors:
            console.print(f"[red]✗ fixture error: {fe}[/red]")

    if errors:
        for slug, msg in errors:
            console.print(f"[red]✗ {slug}[/red]\n{msg}\n")

    if errors or fixture_errors:
        sys.exit(1)

    console.print(f"[green]OK[/green] — validated {len(slugs)} process(es)")
