"""pdm test — run BP integration test cases via sandbox."""

import json
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

import click
from rich.console import Console

from ..config import load_config
from ..sandbox_lifecycle import (
    SandboxNotRunningError,
    bring_down_sandbox,
    bring_up_sandbox,
    ensure_sandbox_up,
)
from ..test_case import load_test_case
from ..test_runner.runner import RunnerContext, run_case

console = Console()


def _assertion_to_dict(a) -> dict:
    if is_dataclass(a):
        return asdict(a)
    if hasattr(a, "model_dump"):
        return a.model_dump()
    if isinstance(a, dict):
        return a
    return {"repr": repr(a)}


@click.command("test")
@click.option(
    "--bp", "bp_slug", default=None,
    help="Run only this BP (default: all).",
)
@click.option(
    "--case", "case_slug", default=None,
    help="Run only this case (default: all cases of selected BPs).",
)
@click.option(
    "--ephemeral", is_flag=True, default=False,
    help="Bring up sandbox, run, tear down.",
)
@click.option(
    "--keep", is_flag=True, default=False,
    help="With --ephemeral: leave sandbox running after.",
)
@click.pass_context
def test(ctx, bp_slug, case_slug, ephemeral, keep):
    """Run integration test cases against the sandbox stack."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    cfg = load_config(cwd)

    if ephemeral:
        try:
            bring_up_sandbox()
        except Exception as e:
            console.print(f"[red]Failed to bring up sandbox: {e}[/red]")
            sys.exit(2)
    else:
        try:
            ensure_sandbox_up()
        except SandboxNotRunningError as e:
            console.print(f"[red]{e}[/red]")
            sys.exit(2)

    try:
        runner_ctx = RunnerContext(
            hoverfly_admin=cfg.hoverfly_admin,
            ssh_replay_journal=cfg.ssh_replay_journal,
            sandbox_db_dsn=cfg.sandbox_db_dsn,
            pdm_api_base=cfg.endpoint("sandbox"),
            pdm_api_key=cfg.api_key("sandbox"),
            cli_bypass_secret=cfg.cli_bypass_secret,
            ssh_override_dir=str(cwd / ".pdm" / "sandbox" / "ssh-overrides"),
        )
    except Exception as e:
        console.print(f"[red]Sandbox config error: {e}[/red]")
        if ephemeral and not keep:
            bring_down_sandbox()
        sys.exit(2)

    proc_root = cwd / "processes"
    if not proc_root.is_dir():
        console.print(f"[yellow]No processes/ directory at {proc_root}[/yellow]")
        bp_dirs: list[Path] = []
    elif bp_slug:
        bp_dirs = [proc_root / bp_slug]
    else:
        bp_dirs = sorted(d for d in proc_root.iterdir() if d.is_dir())

    results = []
    try:
        for bp_dir in bp_dirs:
            tests_dir = bp_dir / "tests"
            if not tests_dir.is_dir():
                continue
            case_files = (
                [tests_dir / f"{case_slug}.yaml"] if case_slug
                else sorted(tests_dir.glob("*.yaml"))
            )
            for cf in case_files:
                if not cf.is_file():
                    console.print(f"[yellow]Case file not found: {cf}[/yellow]")
                    continue
                try:
                    tc = load_test_case(cf)
                except Exception as e:
                    console.print(
                        f"  [red]load failed:[/red] {bp_dir.name}/{cf.stem}: {e}"
                    )
                    from ..test_runner.runner import CaseResult
                    results.append(CaseResult(
                        bp=bp_dir.name,
                        case=cf.stem,
                        run_id=None,
                        status="error",
                        error=f"load_test_case failed: {e}",
                    ))
                    continue
                console.print(f"  running {bp_dir.name}/{tc.name}…")
                loaded_fixtures: list[str] = []
                if tc.fixtures:
                    from ..fixtures.loader import load_fixtures_for_case
                    try:
                        loaded_fixtures = load_fixtures_for_case(tc, bp_dir, runner_ctx)
                    except RuntimeError as e:
                        from ..test_runner.runner import CaseResult
                        console.print(f"  [red]fixture load error:[/red] {e}")
                        results.append(CaseResult(
                            bp=bp_dir.name,
                            case=tc.name,
                            run_id=None,
                            status="error",
                            error=f"fixture load failed: {e}",
                        ))
                        continue
                try:
                    res = run_case(tc, bp_slug=bp_dir.name, ctx=runner_ctx)
                finally:
                    if loaded_fixtures:
                        from ..fixtures.loader import unload_fixtures_for_case
                        unload_fixtures_for_case(loaded_fixtures, runner_ctx)
                results.append(res)
                colour = "green" if res.status == "passed" else "red"
                console.print(f"    [{colour}]→ {res.status}[/{colour}]")
    finally:
        last_run = {
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cases": [
                {
                    "bp": r.bp,
                    "case": r.case,
                    "run_id": r.run_id,
                    "status": r.status,
                    "process_status": r.process_status,
                    "error": r.error,
                    "assertions": [_assertion_to_dict(a) for a in r.assertions],
                }
                for r in results
            ],
        }
        (cwd / ".pdm").mkdir(exist_ok=True)
        (cwd / ".pdm" / "last-run.json").write_text(
            json.dumps(last_run, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        if ephemeral and not keep:
            try:
                bring_down_sandbox()
            except Exception as e:
                console.print(f"[yellow]bring_down_sandbox failed: {e}[/yellow]")

    has_error = any(r.status == "error" for r in results)
    has_failed = any(r.status in {"failed", "timeout"} for r in results)
    if has_error:
        sys.exit(2)
    if has_failed:
        sys.exit(1)
    sys.exit(0)
