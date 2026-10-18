"""Celery-compatible snapshot generation task (Etap 10 Phase 3 — T016).

This module provides a function that can be called from a Celery beat task
on the backend side, OR directly from the CLI. It reuses the same
snapshot_writer logic.

For the backend Celery integration, see:
  pdm/backend/processes/tasks.py :: generate_weekly_telemetry_snapshots
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .snapshot_writer import render_snapshot, snapshot_path


def generate_snapshots_for_week(
    *,
    fetch_aggregates,
    list_bp_slugs,
    output_root: Path,
    iso_week: str | None = None,
    generated_at: str | None = None,
) -> dict:
    """Generate snapshot files for all BPs for a given ISO week.

    Parameters
    ----------
    fetch_aggregates : callable(bp_slug, since, until) -> dict
        Function that returns aggregates data for a BP and time window.
    list_bp_slugs : callable() -> list[str]
        Function that returns all known BP slugs.
    output_root : Path
        Root directory of the client-project repo.
    iso_week : str, optional
        ISO week string (e.g. "2026-W20"). Defaults to previous completed week.
    generated_at : str, optional
        Override timestamp for deterministic output.

    Returns
    -------
    dict
        {"written": [...], "unchanged": [...], "empty": [...]}
    """
    if iso_week is None:
        iso_week = _previous_iso_week()

    if generated_at is None:
        generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    since, until = iso_week_bounds(iso_week)
    slugs = list_bp_slugs()

    result = {"written": [], "unchanged": [], "empty": []}

    for slug in slugs:
        aggregates = fetch_aggregates(slug, since, until)

        # Empty window policy: write an explicit empty snapshot
        # (spec says "writes an explicit empty snapshot according to documented policy")
        total = aggregates.get("total_count", 0)

        md = render_snapshot(
            aggregates=aggregates,
            bp_slug=slug,
            iso_week=iso_week,
            generated_at=generated_at,
        )

        out_path = output_root / snapshot_path(iso_week, slug)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Idempotency: skip write if content is identical
        if out_path.is_file():
            existing = out_path.read_text(encoding="utf-8")
            if existing == md:
                result["unchanged"].append(slug)
                continue

        out_path.write_text(md, encoding="utf-8")
        if total == 0:
            result["empty"].append(slug)
        else:
            result["written"].append(slug)

    return result


def iso_week_bounds(iso_week: str) -> tuple[str, str]:
    """Parse 'YYYY-Www' into (since_iso, until_iso) UTC timestamps."""
    from datetime import date

    parts = iso_week.split("-W")
    year = int(parts[0])
    week = int(parts[1])

    jan4 = date(year, 1, 4)
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


def _previous_iso_week() -> str:
    """Return the previous completed ISO week as 'YYYY-Www'."""
    today = datetime.now(timezone.utc).date()
    days_since_monday = today.weekday()
    last_monday = today - timedelta(days=days_since_monday)
    prev_monday = last_monday - timedelta(days=7)
    iso_year, iso_week_num, _ = prev_monday.isocalendar()
    return f"{iso_year}-W{iso_week_num:02d}"
