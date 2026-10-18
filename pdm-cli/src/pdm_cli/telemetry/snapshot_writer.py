"""Snapshot writer — renders aggregates API response into deterministic markdown.

Design (T013):
- Input: aggregates dict (as returned by GET /api/runs/aggregates/) + metadata.
- Output: UTF-8 markdown string, byte-stable for identical inputs.
- Determinism: all lists are sorted, floats rounded, no timestamps that vary
  between runs (generated_at is passed in, not computed internally).

FR-009, FR-010, FR-011, FR-012 from spec.md.
"""

from __future__ import annotations

from datetime import datetime


def render_snapshot(
    *,
    aggregates: dict,
    bp_slug: str,
    iso_week: str,
    generated_at: str,
) -> str:
    """Render a telemetry snapshot as deterministic markdown.

    Parameters
    ----------
    aggregates : dict
        Response from GET /api/runs/aggregates/ (or equivalent shape).
    bp_slug : str
        Business process slug (used in heading and filename).
    iso_week : str
        ISO week string, e.g. "2026-W20".
    generated_at : str
        ISO timestamp of generation (for reproducibility, caller provides it).

    Returns
    -------
    str
        Markdown content for feedback/telemetry/{iso_week}-{bp_slug}.md
    """
    window = aggregates.get("window", {})
    since = window.get("since", "?")
    until = window.get("until", "?")

    total_count = aggregates.get("total_count", 0)
    by_status = aggregates.get("by_status", {})
    duration_ms = aggregates.get("duration_ms", {})
    top_failing = aggregates.get("top_failing_steps", [])
    orphan_hosts = aggregates.get("top_orphan_egress_hosts", [])
    egress_volume = aggregates.get("egress_volume", {}).get("per_run", {})
    assignment_breakdown = aggregates.get("assignment_status_breakdown_by_step", [])

    lines: list[str] = []

    # Header
    lines.append(f"# Telemetry Snapshot: {bp_slug} — {iso_week}")
    lines.append("")
    lines.append(f"- **Generated**: {generated_at}")
    lines.append(f"- **Window**: {since} → {until}")
    lines.append(f"- **Business Process**: `{bp_slug}`")
    lines.append("")

    # Counts & Status Breakdown
    lines.append("## Counts & Status Breakdown")
    lines.append("")
    lines.append(f"- **Total runs**: {total_count}")
    if by_status:
        for status in sorted(by_status.keys()):
            lines.append(f"  - {status}: {by_status[status]}")
    else:
        lines.append("  - _(no runs in window)_")
    lines.append("")

    # Duration Percentiles
    lines.append("## Duration Percentiles (ms)")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    for key in ("p50", "p95", "p99"):
        val = duration_ms.get(key)
        display = str(val) if val is not None else "—"
        lines.append(f"| {key} | {display} |")
    lines.append("")

    # Top Failing Steps
    lines.append("## Top Failing Steps")
    lines.append("")
    if top_failing:
        lines.append("| Step | Failed | Total | Rate |")
        lines.append("|------|--------|-------|------|")
        for step in top_failing:
            label = step.get("step_label", "?")
            failed = step.get("failed_count", 0)
            total = step.get("total_count", 0)
            rate = f"{failed / total * 100:.0f}%" if total > 0 else "—"
            lines.append(f"| {label} | {failed} | {total} | {rate} |")
    else:
        lines.append("_(no failing steps)_")
    lines.append("")

    # Orphan Egress Hosts
    lines.append("## Orphan Egress Hosts")
    lines.append("")
    if orphan_hosts:
        lines.append("| Host | Kind | Count |")
        lines.append("|------|------|-------|")
        for entry in orphan_hosts:
            lines.append(
                f"| {entry.get('host', '?')} "
                f"| {entry.get('kind', '?')} "
                f"| {entry.get('count', 0)} |"
            )
    else:
        lines.append("_(no orphan egress)_")
    lines.append("")

    # Egress Volume Per Run
    lines.append("## Egress Volume Per Run")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    for key in ("http_p50", "http_p95", "ssh_p50", "ssh_p95"):
        val = egress_volume.get(key)
        display = str(val) if val is not None else "—"
        lines.append(f"| {key} | {display} |")
    lines.append("")

    # Assignment Status Breakdown
    lines.append("## Assignment Status Breakdown")
    lines.append("")
    if assignment_breakdown:
        statuses = ["pending", "ready", "in_progress", "completed", "error", "suspended"]
        header = "| Step | " + " | ".join(statuses) + " |"
        sep = "|------|" + "|".join(["------"] * len(statuses)) + "|"
        lines.append(header)
        lines.append(sep)
        for row in assignment_breakdown:
            label = row.get("step_label", "?")
            cells = " | ".join(str(row.get(s, 0)) for s in statuses)
            lines.append(f"| {label} | {cells} |")
    else:
        lines.append("_(no assignments)_")
    lines.append("")

    return "\n".join(lines)


def snapshot_filename(iso_week: str, bp_slug: str) -> str:
    """Return the canonical filename for a snapshot: YYYY-Www-<bp>.md."""
    return f"{iso_week}-{bp_slug}.md"


def snapshot_path(iso_week: str, bp_slug: str) -> str:
    """Return the relative path under the client-project repo."""
    return f"feedback/telemetry/{snapshot_filename(iso_week, bp_slug)}"
