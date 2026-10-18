"""pdm telemetry — weekly telemetry snapshot commands (Etap 10 Phase 3).

Subcommands:
  pdm telemetry snapshot  — generate weekly markdown snapshots from aggregates API.

Design Decision (T017 — FR-021):
  `pdm telemetry pull` is NOT implemented as a separate command.
  Rationale: `pdm telemetry snapshot` already fulfills the same role — it pulls
  aggregates from the PDM API and writes deterministic markdown into the
  client-project repo at feedback/telemetry/YYYY-Www-<bp>.md.

  A separate `pull` verb would be redundant because:
  1. The aggregates API is the only telemetry source (no separate telemetry store).
  2. The snapshot command already handles BP filtering, week selection, and
     idempotent file writes.
  3. MCP tools (pdm:run-aggregates) provide interactive access for agents that
     don't need local files.

  If a future requirement introduces a distinct telemetry data source (e.g.
  Prometheus metrics, external APM), a `pdm telemetry pull` command can be
  added at that point with a clear data-source distinction.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click

from ..api_client import PdmApiClient
from ..config import load_config
from ..telemetry.snapshot_writer import render_snapshot, snapshot_path


def _iso_week_bounds(iso_week: str) -> tuple[str, str]:
    """Parse 'YYYY-Www' into (monday_iso, next_monday_iso) timestamps."""
    # e.g. "2026-W20" → year=2026, week=20
    parts = iso_week.split("-W")
    year = int(parts[0])
    week = int(parts[1])
    # ISO week: Monday is day 1
    monday = datetime.strptime(f"{year}-W{week:02d}-1", "%Y-W%W-%w")
    # strptime %W is zero-indexed; use ISO calendar instead
    from datetime import date

    jan4 = date(year, 1, 4)  # Jan 4 is always in ISO week 1
    # Monday of ISO week 1
    week1_monday = jan4 - timedelta(days=jan4.isoweekday() - 1)
    target_monday = week1_monday + timedelta(weeks=week - 1)
    next_monday = target_monday + timedelta(days=7)

    since = datetime(
        target_monday.year, target_monday.month, target_monday.day,
        tzinfo=timezone.utc,
    )
    until = datetime(
        next_monday.year, next_monday.month, next_monday.day,
        tzinfo=timezone.utc,
    )
    return since.isoformat(), until.isoformat()


def _current_iso_week() -> str:
    """Return the previous completed ISO week as 'YYYY-Www'."""
    today = datetime.now(timezone.utc).date()
    # Go back to last Monday, then one more week to get the *completed* week
    days_since_monday = today.weekday()  # 0=Mon
    last_monday = today - timedelta(days=days_since_monday)
    prev_monday = last_monday - timedelta(days=7)
    iso_year, iso_week_num, _ = prev_monday.isocalendar()
    return f"{iso_year}-W{iso_week_num:02d}"


@click.group("telemetry")
def telemetry():
    """Telemetry snapshot commands."""
    pass


@telemetry.command("snapshot")
@click.option("--week", default=None,
              help="ISO week to snapshot, e.g. 2026-W20. Default: previous completed week.")
@click.option("--bp", "bp_slugs", multiple=True,
              help="Filter to specific BP slug(s). Omit for all known BPs.")
@click.option("--env", default="prod", show_default=True,
              help="PDM environment name from pdm.config.yaml endpoints.")
@click.option("--dry-run", is_flag=True,
              help="Print markdown to stdout instead of writing files.")
@click.option("--generated-at", "generated_at_override", default=None,
              help="Override generated_at timestamp (for deterministic replay).")
@click.pass_context
def snapshot_cmd(ctx, week, bp_slugs, env, dry_run, generated_at_override):
    """Generate weekly telemetry snapshot(s) from the aggregates API.

    Writes feedback/telemetry/YYYY-Www-<bp>.md for each business process.
    Idempotent: re-running with the same --week and --generated-at produces
    identical output (no noisy diffs).
    """
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    cfg = load_config(cwd)

    iso_week = week or _current_iso_week()
    since, until = _iso_week_bounds(iso_week)

    generated_at = generated_at_override or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )

    api_key = cfg.api_key(env)
    base_url = cfg.endpoint(env)

    with PdmApiClient(base_url=base_url, api_key=api_key) as client:
        # Determine BP list
        if bp_slugs:
            slugs = list(bp_slugs)
        else:
            # Fetch all BPs from the API
            processes = client.list_processes()
            slugs = sorted(
                p["slug"] for p in processes if p.get("slug")
            )

        if not slugs:
            click.echo("No business processes found.", err=True)
            sys.exit(1)

        written = 0
        for slug in slugs:
            aggregates = client.run_aggregates(
                bp_slug=slug, since=since, until=until,
            )

            md = render_snapshot(
                aggregates=aggregates,
                bp_slug=slug,
                iso_week=iso_week,
                generated_at=generated_at,
            )

            if dry_run:
                click.echo(f"--- {snapshot_path(iso_week, slug)} ---")
                click.echo(md)
            else:
                out_path = cwd / snapshot_path(iso_week, slug)
                out_path.parent.mkdir(parents=True, exist_ok=True)

                # Idempotency: only write if content differs (T015)
                if out_path.is_file():
                    existing = out_path.read_text(encoding="utf-8")
                    if existing == md:
                        click.echo(f"  {slug}: unchanged (skipped)")
                        continue

                out_path.write_text(md, encoding="utf-8")
                click.echo(f"  {slug}: wrote {out_path.relative_to(cwd)}")
                written += 1

        if not dry_run:
            click.echo(f"\nDone: {written} snapshot(s) written for {iso_week}.")
