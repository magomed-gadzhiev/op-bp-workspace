"""Tests for telemetry snapshot generation (Etap 10 Phase 3 — T018).

Covers:
- Snapshot shape (all required sections present)
- Empty windows (explicit empty snapshot written)
- Idempotency (repeated runs produce no diffs)
- BP filtering (only requested BPs get snapshots)
- CLI command integration
"""

from pathlib import Path

import respx
from click.testing import CliRunner

from pdm_cli.cli import main
from pdm_cli.telemetry.snapshot_writer import render_snapshot, snapshot_filename, snapshot_path
from pdm_cli.telemetry.snapshot_task import generate_snapshots_for_week, iso_week_bounds


# --- Fixtures / helpers ---

SAMPLE_AGGREGATES = {
    "window": {"since": "2026-05-11T00:00:00+00:00", "until": "2026-05-18T00:00:00+00:00"},
    "filter": {"bp_slug": "order"},
    "total_count": 42,
    "by_status": {"completed": 30, "error": 7, "running": 5},
    "duration_ms": {"p50": 120000, "p95": 450000, "p99": 900000},
    "mean_duration_ms_per_bp": {"order": 200000},
    "top_failing_steps": [
        {"step_id": 1, "step_label": "validate-input", "failed_count": 5, "total_count": 42},
        {"step_id": 2, "step_label": "call-erp", "failed_count": 2, "total_count": 42},
    ],
    "top_orphan_egress_hosts": [
        {"host": "legacy-erp.internal", "kind": "http", "count": 23},
        {"host": "sftp.partner.com", "kind": "ssh", "count": 4},
    ],
    "egress_volume": {
        "per_run": {"http_p50": 5, "http_p95": 12, "ssh_p50": 2, "ssh_p95": 4}
    },
    "assignment_status_breakdown_by_step": [
        {
            "step_id": 1, "step_label": "validate-input",
            "pending": 0, "ready": 2, "in_progress": 1,
            "completed": 30, "error": 5, "suspended": 0,
        },
        {
            "step_id": 2, "step_label": "call-erp",
            "pending": 1, "ready": 0, "in_progress": 3,
            "completed": 28, "error": 2, "suspended": 0,
        },
    ],
}

EMPTY_AGGREGATES = {
    "window": {"since": "2026-05-11T00:00:00+00:00", "until": "2026-05-18T00:00:00+00:00"},
    "filter": {"bp_slug": "payroll"},
    "total_count": 0,
    "by_status": {},
    "duration_ms": {"p50": None, "p95": None, "p99": None},
    "mean_duration_ms_per_bp": {},
    "top_failing_steps": [],
    "top_orphan_egress_hosts": [],
    "egress_volume": {"per_run": {"http_p50": None, "http_p95": None, "ssh_p50": None, "ssh_p95": None}},
    "assignment_status_breakdown_by_step": [],
}


# --- T018: Snapshot shape tests ---

class TestSnapshotShape:
    """Verify rendered markdown contains all required sections (FR-011)."""

    def test_header_contains_bp_and_week(self):
        md = render_snapshot(
            aggregates=SAMPLE_AGGREGATES,
            bp_slug="order",
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert "# Telemetry Snapshot: order — 2026-W20" in md

    def test_metadata_fields_present(self):
        md = render_snapshot(
            aggregates=SAMPLE_AGGREGATES,
            bp_slug="order",
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert "**Generated**: 2026-05-19T10:00:00+00:00" in md
        assert "**Window**:" in md
        assert "**Business Process**: `order`" in md

    def test_counts_and_status_breakdown(self):
        md = render_snapshot(
            aggregates=SAMPLE_AGGREGATES,
            bp_slug="order",
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert "## Counts & Status Breakdown" in md
        assert "**Total runs**: 42" in md
        assert "completed: 30" in md
        assert "error: 7" in md
        assert "running: 5" in md

    def test_duration_percentiles(self):
        md = render_snapshot(
            aggregates=SAMPLE_AGGREGATES,
            bp_slug="order",
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert "## Duration Percentiles (ms)" in md
        assert "| p50 | 120000 |" in md
        assert "| p95 | 450000 |" in md
        assert "| p99 | 900000 |" in md

    def test_top_failing_steps(self):
        md = render_snapshot(
            aggregates=SAMPLE_AGGREGATES,
            bp_slug="order",
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert "## Top Failing Steps" in md
        assert "validate-input" in md
        assert "call-erp" in md
        # Rate column
        assert "12%" in md  # 5/42 ≈ 12%

    def test_orphan_egress_hosts(self):
        md = render_snapshot(
            aggregates=SAMPLE_AGGREGATES,
            bp_slug="order",
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert "## Orphan Egress Hosts" in md
        assert "legacy-erp.internal" in md
        assert "sftp.partner.com" in md

    def test_egress_volume_per_run(self):
        md = render_snapshot(
            aggregates=SAMPLE_AGGREGATES,
            bp_slug="order",
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert "## Egress Volume Per Run" in md
        assert "| http_p50 | 5 |" in md
        assert "| ssh_p95 | 4 |" in md

    def test_assignment_status_breakdown(self):
        md = render_snapshot(
            aggregates=SAMPLE_AGGREGATES,
            bp_slug="order",
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert "## Assignment Status Breakdown" in md
        assert "validate-input" in md
        assert "call-erp" in md


# --- T018: Empty window tests ---

class TestEmptyWindow:
    """Verify behavior when no runs exist for a BP in the period."""

    def test_empty_snapshot_has_zero_total(self):
        md = render_snapshot(
            aggregates=EMPTY_AGGREGATES,
            bp_slug="payroll",
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert "**Total runs**: 0" in md

    def test_empty_snapshot_shows_no_runs_marker(self):
        md = render_snapshot(
            aggregates=EMPTY_AGGREGATES,
            bp_slug="payroll",
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert "_(no runs in window)_" in md

    def test_empty_snapshot_shows_dash_for_percentiles(self):
        md = render_snapshot(
            aggregates=EMPTY_AGGREGATES,
            bp_slug="payroll",
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert "| p50 | — |" in md

    def test_empty_snapshot_no_failing_steps(self):
        md = render_snapshot(
            aggregates=EMPTY_AGGREGATES,
            bp_slug="payroll",
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert "_(no failing steps)_" in md

    def test_empty_snapshot_written_to_disk(self, tmp_path: Path):
        """Empty windows produce an explicit file (not omitted)."""
        result = generate_snapshots_for_week(
            fetch_aggregates=lambda slug, since, until: EMPTY_AGGREGATES,
            list_bp_slugs=lambda: ["payroll"],
            output_root=tmp_path,
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert "payroll" in result["empty"]
        out = tmp_path / "feedback" / "telemetry" / "2026-W20-payroll.md"
        assert out.is_file()
        assert "**Total runs**: 0" in out.read_text(encoding="utf-8")


# --- T018: Idempotency tests ---

class TestIdempotency:
    """Verify repeated runs do not create noisy diffs (FR-012, NFR-001)."""

    def test_same_input_produces_identical_output(self):
        """Determinism: same aggregates + metadata → same bytes."""
        kwargs = dict(
            aggregates=SAMPLE_AGGREGATES,
            bp_slug="order",
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        md1 = render_snapshot(**kwargs)
        md2 = render_snapshot(**kwargs)
        assert md1 == md2

    def test_repeated_generation_skips_unchanged(self, tmp_path: Path):
        """Second run with same data reports 'unchanged', no file rewrite."""
        kwargs = dict(
            fetch_aggregates=lambda slug, since, until: SAMPLE_AGGREGATES,
            list_bp_slugs=lambda: ["order"],
            output_root=tmp_path,
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        r1 = generate_snapshots_for_week(**kwargs)
        assert "order" in r1["written"]

        r2 = generate_snapshots_for_week(**kwargs)
        assert "order" in r2["unchanged"]
        assert "order" not in r2["written"]

    def test_changed_data_overwrites(self, tmp_path: Path):
        """If aggregates change, file is rewritten."""
        kwargs_base = dict(
            list_bp_slugs=lambda: ["order"],
            output_root=tmp_path,
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        generate_snapshots_for_week(
            fetch_aggregates=lambda slug, since, until: SAMPLE_AGGREGATES,
            **kwargs_base,
        )

        # Change total_count
        modified = dict(SAMPLE_AGGREGATES)
        modified["total_count"] = 99
        r2 = generate_snapshots_for_week(
            fetch_aggregates=lambda slug, since, until: modified,
            **kwargs_base,
        )
        assert "order" in r2["written"]


# --- T018: BP filtering tests ---

class TestBpFiltering:
    """Verify that only requested BPs get snapshots."""

    def test_multiple_bps_each_get_file(self, tmp_path: Path):
        def fetch(slug, since, until):
            if slug == "order":
                return SAMPLE_AGGREGATES
            return EMPTY_AGGREGATES

        result = generate_snapshots_for_week(
            fetch_aggregates=fetch,
            list_bp_slugs=lambda: ["order", "payroll"],
            output_root=tmp_path,
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert (tmp_path / "feedback" / "telemetry" / "2026-W20-order.md").is_file()
        assert (tmp_path / "feedback" / "telemetry" / "2026-W20-payroll.md").is_file()

    def test_single_bp_filter(self, tmp_path: Path):
        """When list_bp_slugs returns one slug, only that file is created."""
        result = generate_snapshots_for_week(
            fetch_aggregates=lambda slug, since, until: SAMPLE_AGGREGATES,
            list_bp_slugs=lambda: ["order"],
            output_root=tmp_path,
            iso_week="2026-W20",
            generated_at="2026-05-19T10:00:00+00:00",
        )
        assert (tmp_path / "feedback" / "telemetry" / "2026-W20-order.md").is_file()
        assert not (tmp_path / "feedback" / "telemetry" / "2026-W20-payroll.md").exists()


# --- Helpers tests ---

class TestHelpers:
    """Test utility functions."""

    def test_snapshot_filename(self):
        assert snapshot_filename("2026-W20", "order") == "2026-W20-order.md"

    def test_snapshot_path(self):
        assert snapshot_path("2026-W20", "order") == "feedback/telemetry/2026-W20-order.md"

    def test_iso_week_bounds_w01(self):
        since, until = iso_week_bounds("2026-W01")
        # 2026-W01 Monday is 2025-12-29
        assert "2025-12-29" in since
        assert "2026-01-05" in until

    def test_iso_week_bounds_w20(self):
        since, until = iso_week_bounds("2026-W20")
        assert "2026-05-11" in since
        assert "2026-05-18" in until


# --- CLI integration tests ---

PROD = "https://prod.local"


class TestCliCommand:
    """Test `pdm telemetry snapshot` CLI command."""

    @respx.mock
    def test_snapshot_dry_run(self, tmp_path: Path):
        """--dry-run prints markdown without writing files."""
        # Setup config
        (tmp_path / "pdm.config.yaml").write_text(
            "endpoints:\n  prod: https://prod.local\n", encoding="utf-8"
        )
        (tmp_path / ".pdm").mkdir()
        (tmp_path / ".pdm" / "secrets.yaml").write_text(
            "api_key_prod: test-key\n", encoding="utf-8"
        )

        respx.get(f"{PROD}/api/business-processes/").respond(
            json=[{"slug": "order", "name": "Order"}]
        )
        respx.get(f"{PROD}/api/runs/aggregates/").respond(json=SAMPLE_AGGREGATES)

        runner = CliRunner()
        result = runner.invoke(main, [
            "telemetry", "snapshot",
            "--week", "2026-W20",
            "--dry-run",
            "--generated-at", "2026-05-19T10:00:00+00:00",
        ], obj={"cwd": tmp_path})

        assert result.exit_code == 0, result.output
        assert "Telemetry Snapshot: order" in result.output
        # No file written in dry-run
        assert not (tmp_path / "feedback" / "telemetry" / "2026-W20-order.md").exists()

    @respx.mock
    def test_snapshot_writes_file(self, tmp_path: Path):
        """Normal run writes the snapshot file."""
        (tmp_path / "pdm.config.yaml").write_text(
            "endpoints:\n  prod: https://prod.local\n", encoding="utf-8"
        )
        (tmp_path / ".pdm").mkdir()
        (tmp_path / ".pdm" / "secrets.yaml").write_text(
            "api_key_prod: test-key\n", encoding="utf-8"
        )

        respx.get(f"{PROD}/api/business-processes/").respond(
            json=[{"slug": "order", "name": "Order"}]
        )
        respx.get(f"{PROD}/api/runs/aggregates/").respond(json=SAMPLE_AGGREGATES)

        runner = CliRunner()
        result = runner.invoke(main, [
            "telemetry", "snapshot",
            "--week", "2026-W20",
            "--generated-at", "2026-05-19T10:00:00+00:00",
        ], obj={"cwd": tmp_path})

        assert result.exit_code == 0, result.output
        out = tmp_path / "feedback" / "telemetry" / "2026-W20-order.md"
        assert out.is_file()
        content = out.read_text(encoding="utf-8")
        assert "# Telemetry Snapshot: order — 2026-W20" in content

    @respx.mock
    def test_snapshot_bp_filter(self, tmp_path: Path):
        """--bp flag limits which BPs are snapshotted."""
        (tmp_path / "pdm.config.yaml").write_text(
            "endpoints:\n  prod: https://prod.local\n", encoding="utf-8"
        )
        (tmp_path / ".pdm").mkdir()
        (tmp_path / ".pdm" / "secrets.yaml").write_text(
            "api_key_prod: test-key\n", encoding="utf-8"
        )

        # Only aggregates for 'order' should be called
        respx.get(f"{PROD}/api/runs/aggregates/").respond(json=SAMPLE_AGGREGATES)

        runner = CliRunner()
        result = runner.invoke(main, [
            "telemetry", "snapshot",
            "--week", "2026-W20",
            "--bp", "order",
            "--generated-at", "2026-05-19T10:00:00+00:00",
        ], obj={"cwd": tmp_path})

        assert result.exit_code == 0, result.output
        assert (tmp_path / "feedback" / "telemetry" / "2026-W20-order.md").is_file()

    @respx.mock
    def test_snapshot_idempotent_second_run(self, tmp_path: Path):
        """Second run with same data reports 'unchanged'."""
        (tmp_path / "pdm.config.yaml").write_text(
            "endpoints:\n  prod: https://prod.local\n", encoding="utf-8"
        )
        (tmp_path / ".pdm").mkdir()
        (tmp_path / ".pdm" / "secrets.yaml").write_text(
            "api_key_prod: test-key\n", encoding="utf-8"
        )

        respx.get(f"{PROD}/api/business-processes/").respond(
            json=[{"slug": "order", "name": "Order"}]
        )
        respx.get(f"{PROD}/api/runs/aggregates/").respond(json=SAMPLE_AGGREGATES)

        runner = CliRunner()
        invoke_args = [
            "telemetry", "snapshot",
            "--week", "2026-W20",
            "--generated-at", "2026-05-19T10:00:00+00:00",
        ]

        # First run
        result1 = runner.invoke(main, invoke_args, obj={"cwd": tmp_path})
        assert result1.exit_code == 0

        # Second run — should report unchanged
        result2 = runner.invoke(main, invoke_args, obj={"cwd": tmp_path})
        assert result2.exit_code == 0
        assert "unchanged" in result2.output
