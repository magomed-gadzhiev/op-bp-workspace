"""`pdm mcp serve --env=...` is a dispatchable subcommand."""

import subprocess
import sys


def test_pdm_mcp_help_runs():
    r = subprocess.run(
        [sys.executable, "-m", "pdm_cli", "mcp", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "serve" in r.stdout


def test_pdm_mcp_serve_help_runs():
    r = subprocess.run(
        [sys.executable, "-m", "pdm_cli", "mcp", "serve", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "--env" in r.stdout


def test_require_mcp_sdk_exits_when_missing(monkeypatch):
    import sys as _sys
    # Force ImportError on mcp module imports
    for k in list(_sys.modules.keys()):
        if k == "mcp" or k.startswith("mcp."):
            monkeypatch.delitem(_sys.modules, k, raising=False)
    monkeypatch.setitem(_sys.modules, "mcp", None)
    monkeypatch.setitem(_sys.modules, "mcp.server", None)
    monkeypatch.setitem(_sys.modules, "mcp.server.fastmcp", None)

    from pdm_cli.mcp.cli import _require_mcp_sdk
    import pytest
    with pytest.raises(SystemExit) as exc:
        _require_mcp_sdk()
    assert exc.value.code != 0
