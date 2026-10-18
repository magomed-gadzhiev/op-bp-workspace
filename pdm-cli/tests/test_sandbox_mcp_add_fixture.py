"""Etap 7 Phase 4 — sandbox.add_fixture tool with HTTP hot-reload."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from pdm_cli.sandbox_mcp.tools.fixtures import _impl_add_fixture


class _Null:
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _ctx(repo):
    return {
        "repo_root": repo,
        "hoverfly_admin": "http://hf",
        "ssh_replay_journal": "http://ssh",
        "ssh_override_dir": repo / "ssh-ov",
        "mutex": _Null(),
    }


def test_add_fixture_http_appends_and_triggers_hot_reload():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "processes" / "bp").mkdir(parents=True)
        with patch("pdm_cli.sandbox_mcp.tools.fixtures.httpx") as hx:
            hx.get.return_value.json.return_value = {"data": {"pairs": []}, "meta": {}}
            out = _impl_add_fixture(
                _ctx(repo), bp="bp", kind="http",
                matcher={"method": "GET", "host": "x", "path": "/y"},
                response={"status": 200},
            )
        assert out["conflict"] is None
        hx.put.assert_called_once()


def test_add_fixture_ssh_writes_file_only_no_hot_reload():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "processes" / "bp").mkdir(parents=True)
        with patch("pdm_cli.sandbox_mcp.tools.fixtures.httpx") as hx:
            out = _impl_add_fixture(
                _ctx(repo), bp="bp", kind="ssh",
                matcher={"host": "h", "command_matches": "cmd"},
                response={"stdout": "ok", "exit_code": 0},
            )
        assert out["conflict"] is None
        hx.put.assert_not_called()
        hx.get.assert_not_called()


def test_add_fixture_returns_conflict_when_duplicate_in_main():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        d = repo / "processes" / "bp" / "fixtures"
        d.mkdir(parents=True)
        (d / "http-main.yaml").write_text(
            "matchers:\n  - request: {method: GET, host: x, path: /y}\n    response: {status: 200}\n"
        )
        with patch("pdm_cli.sandbox_mcp.tools.fixtures.httpx"):
            out = _impl_add_fixture(
                _ctx(repo), bp="bp", kind="http",
                matcher={"method": "GET", "host": "x", "path": "/y"},
                response={"status": 200},
            )
        assert out["conflict"]["kind"] == "exact_match_exists"
