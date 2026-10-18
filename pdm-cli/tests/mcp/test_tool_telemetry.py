from unittest.mock import MagicMock
from pdm_cli.mcp.tools.telemetry import (
    do_get_run_details,
    do_get_telemetry_aggregates,
    do_search_telemetry,
)


def test_search_telemetry_passes_filters():
    api = MagicMock()
    api.list_runs.return_value = {
        "bp_slug": "payroll", "total": 1, "by_status": {"error": 1},
        "runs": [{"run_id": 7, "status": "error"}],
    }
    out = do_search_telemetry(
        api, journals=None, bp_slug="payroll", since="7d", status="error",
    )
    api.list_runs.assert_called_once_with(
        "payroll", since="7d", until=None, status="error", limit=50, offset=0,
    )
    assert out["runs"][0]["run_id"] == 7
    assert "sandbox_runs" not in out


def test_search_telemetry_includes_sandbox_runs_when_journals_set():
    api = MagicMock()
    api.list_runs.return_value = {"runs": [], "total": 0, "by_status": {}}
    journals = MagicMock()
    journals.list_recent.return_value = [42, 41]
    out = do_search_telemetry(api, journals=journals, bp_slug="x", since="1h")
    assert out["sandbox_runs"] == [{"run_id": 42}, {"run_id": 41}]


def test_run_details_prod_mode():
    api = MagicMock()
    api.run_details.return_value = {
        "run_id": 42, "status": "completed",
        "egress": {"http": [{"url": "x"}], "ssh": [], "orphan_count": {"http": 0, "ssh": 0}},
    }
    out = do_get_run_details(api, journals=None, run_id=42)
    assert out["egress_source"] == "prod-db"
    assert out["egress"]["http"] == [{"url": "x"}]


def test_run_details_sandbox_merge_when_journal_exists():
    api = MagicMock()
    api.run_details.return_value = {
        "run_id": 42, "status": "completed",
        "egress": {"http": [], "ssh": [], "orphan_count": {"http": 0, "ssh": 0}},
    }
    journals = MagicMock()
    journals.read.return_value = {
        "http": [{"method": "GET", "url": "y", "status": 200,
                  "duration_ms": 1, "started_at": "2026-05-14T10:00:00Z",
                  "source": "pdm-script"}],
        "ssh": [],
    }
    out = do_get_run_details(api, journals=journals, run_id=42)
    assert out["egress_source"] == "merged"
    assert len(out["egress"]["http"]) == 1
    assert out["egress"]["http"][0]["url"] == "y"


def test_get_telemetry_aggregates_delegates_to_api():
    api = MagicMock()
    api.run_aggregates.return_value = {"total_count": 42}

    out = do_get_telemetry_aggregates(
        api, bp_slug="payroll", since="2026-05-01T00:00:00Z",
        until="2026-05-15T00:00:00Z",
    )

    api.run_aggregates.assert_called_once_with(
        bp_slug="payroll", since="2026-05-01T00:00:00Z",
        until="2026-05-15T00:00:00Z",
    )
    assert out == {"total_count": 42}
