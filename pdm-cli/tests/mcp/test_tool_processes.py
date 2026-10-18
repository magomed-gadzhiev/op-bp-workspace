"""processes tool functions called directly (no MCP wire-layer)."""

from unittest.mock import MagicMock

from pdm_cli.mcp.tools.processes import (
    do_list_processes, do_get_process_summary, do_get_process,
)


def test_list_processes_passes_through():
    api = MagicMock()
    api.list_processes.return_value = [
        {"slug": "a", "status": "published", "version": "v1", "owner": "x"},
    ]
    out = do_list_processes(api)
    assert out == [{"slug": "a", "status": "published", "version": "v1", "owner": "x", "last_modified": None}]


def test_list_processes_filters_by_status():
    api = MagicMock()
    api.list_processes.return_value = [
        {"slug": "a", "status": "draft"},
        {"slug": "b", "status": "published"},
    ]
    out = do_list_processes(api, status="published")
    assert [p["slug"] for p in out] == ["b"]


def test_get_process_summary_extracts_slugs():
    api = MagicMock()
    api.get_full.return_value.model_dump.return_value = {
        "manifest": {"slug": "payroll", "name": "Payroll"},
        "entities": [{"slug": "employee"}, {"slug": "payroll_record"}],
        "tasks": [{"slug": "calc_bonus"}, {"slug": "approve"}],
        "scripts": [{"name": "check_contract"}],
        "workflows": [{"name": "main"}],
        "templates": [{"name": "payslip.html"}],
    }
    out = do_get_process_summary(api, slug="payroll")
    assert out["slug"] == "payroll"
    assert out["entities"] == ["employee", "payroll_record"]
    assert out["tasks"] == ["calc_bonus", "approve"]
    assert out["scripts"] == ["check_contract"]


def test_get_process_full_passes_through():
    api = MagicMock()
    api.get_full.return_value.model_dump.return_value = {"manifest": {"slug": "x"}}
    out = do_get_process(api, slug="x")
    assert out == {"manifest": {"slug": "x"}}
