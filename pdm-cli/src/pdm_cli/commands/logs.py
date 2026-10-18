"""pdm logs <run_id> — assemble JSON snapshot from all sandbox sources.

Sources combined into a single JSON payload:
  - matching case entry from .pdm/last-run.json (if run_id is the last run);
  - Hoverfly journal (HTTP egress) — only for the last run (cleared otherwise);
  - ssh-replay journal (SSH egress) — only for the last run (cleared otherwise);
  - process_instance from PDM sandbox API (regardless of last-run status);
  - container logs (tail) for required sandbox services.

Exit codes:
  0 — snapshot assembled and printed
  3 — run_id not found in last-run.json and process_instance API returned 404
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import click
import httpx

from ..config import load_config
from ..sandbox_lifecycle import COMPOSE_FILES, REQUIRED_SERVICES
from ..test_runner.hoverfly_journal import get_journal
from ..test_runner.ssh_journal import get_ssh_journal


_JOURNAL_CLEARED = {"note": "journal cleared (only last run is retained)"}


def _container_logs(service: str, tail: int) -> str:
    cmd = ["docker", "compose"]
    for f in COMPOSE_FILES:
        cmd.extend(["-f", f])
    cmd.extend(["logs", "--no-color", "--tail", str(tail), service])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return r.stdout or ""
    except Exception as e:  # pragma: no cover - defensive
        return f"<failed to fetch logs: {e}>"


def _safe_journal(fetch, base: str):
    try:
        return fetch(base)
    except Exception as e:
        return {"error": f"failed to fetch journal: {e}"}


@click.command("logs")
@click.argument("run_id")
@click.option(
    "--format", "fmt",
    type=click.Choice(["json", "text"]),
    default="json", show_default=True,
)
@click.option(
    "--tail", "tail",
    type=int, default=200, show_default=True,
    help="How many trailing log lines to fetch per container.",
)
@click.pass_context
def logs(ctx, run_id, fmt, tail):
    """Assemble a JSON snapshot of all sandbox sources for RUN_ID."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    cfg = load_config(cwd)

    # 1. Determine is_last_run from .pdm/last-run.json
    last_run_path = cwd / ".pdm" / "last-run.json"
    last_run: dict = {}
    if last_run_path.is_file():
        try:
            last_run = json.loads(last_run_path.read_text("utf-8")) or {}
        except json.JSONDecodeError:
            last_run = {}
    matching_case = next(
        (c for c in last_run.get("cases", []) if c.get("run_id") == run_id),
        None,
    )
    is_last_run = matching_case is not None

    # 2. Fetch process_instance from PDM API regardless of is_last_run.
    pi = None
    pi_status: int | None = None
    try:
        headers = {"Authorization": f"Token {cfg.api_key('sandbox')}"}
        r = httpx.get(
            f"{cfg.endpoint('sandbox')}/api/process-instances/{run_id}/",
            headers=headers, timeout=10,
        )
        pi_status = r.status_code
        if r.status_code == 200:
            pi = r.json()
    except Exception as e:
        pi = {"error": f"failed to fetch process_instance: {e}"}

    # If run_id not found anywhere, exit 3.
    if not is_last_run and pi_status == 404:
        click.echo(json.dumps({
            "error": "run_id not found",
            "run_id": run_id,
            "hint": "see .pdm/last-run.json for recent runs",
        }))
        sys.exit(3)

    # 3. Egress journals — only meaningful for the last run.
    if is_last_run:
        egress_http = _safe_journal(get_journal, cfg.hoverfly_admin)
        egress_ssh = _safe_journal(get_ssh_journal, cfg.ssh_replay_journal)
    else:
        egress_http = dict(_JOURNAL_CLEARED)
        egress_ssh = dict(_JOURNAL_CLEARED)

    # 4. Container logs (tail) for sandbox services.
    containers = {
        svc: _container_logs(svc, tail=tail)
        for svc in REQUIRED_SERVICES
    }

    payload = {
        "run_id": run_id,
        "bp": (matching_case or {}).get("bp"),
        "case": (matching_case or {}).get("case"),
        "status": (matching_case or {}).get("status"),
        "process_status": (matching_case or {}).get("process_status"),
        "is_last_run": is_last_run,
        "process_instance": pi,
        "egress": {"http": egress_http, "ssh": egress_ssh},
        "containers": containers,
        "assertions": (matching_case or {}).get("assertions", []),
    }

    if fmt == "json":
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
        sys.exit(0)

    # Text format: compact human-readable summary.
    click.echo(f"run_id: {run_id} (is_last_run={is_last_run})")
    click.echo(f"bp/case: {payload['bp']}/{payload['case']}")
    click.echo(f"status: {payload['status']}")
    click.echo(f"process_status: {payload['process_status']}")
    click.echo("\n--- assertions ---")
    for a in payload["assertions"] or []:
        kind = a.get("kind", "?") if isinstance(a, dict) else "?"
        status = a.get("status", "?") if isinstance(a, dict) else "?"
        explain = a.get("explain", "") if isinstance(a, dict) else ""
        click.echo(f"  [{status}] {kind}: {explain}")

    http_count = (
        len(egress_http) if isinstance(egress_http, list) else "cleared"
    )
    ssh_count = (
        len(egress_ssh) if isinstance(egress_ssh, list) else "cleared"
    )
    click.echo(f"\n--- egress.http ({http_count}) ---")
    click.echo(f"--- egress.ssh ({ssh_count}) ---")
    click.echo("\n--- containers ---")
    for svc, body in containers.items():
        lines = body.count("\n") if body else 0
        click.echo(f"  {svc}: {lines} lines")
    sys.exit(0)
