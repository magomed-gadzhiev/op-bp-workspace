"""make_server registers all expected tool-calls."""

from unittest.mock import MagicMock
from pathlib import Path

from pdm_cli.mcp.server import make_server


def test_make_server_registers_expected_tools(tmp_path: Path):
    api = MagicMock()
    api.health.return_value = {"pdm_api_version": "1"}
    server = make_server(
        env="prod", repo_root=tmp_path, api=api, journals=None,
        feedback_reader=MagicMock(),
    )
    # FastMCP exposes registered tools — read whatever attr the installed SDK provides.
    # mcp>=1.0 uses `_tool_manager._tools` (dict). Be defensive across versions.
    tool_names: set[str] = set()
    tm = getattr(server, "_tool_manager", None)
    if tm and hasattr(tm, "_tools"):
        tool_names = set(tm._tools.keys())
    else:
        # Try alternative names
        for attr in ("_tools", "tools"):
            t = getattr(server, attr, None)
            if isinstance(t, dict):
                tool_names = set(t.keys())
                break
            if isinstance(t, list):
                tool_names = {getattr(x, "name", None) or getattr(x, "__name__", "?") for x in t}
                break

    expected = {
        "list_processes", "get_process", "get_process_summary",
        "get_entity_schema", "search_telemetry", "get_run_details",
        "get_telemetry_aggregates", "get_feedback",
    }
    assert expected <= tool_names, (
        f"Missing tools: {expected - tool_names}; got: {tool_names}"
    )
