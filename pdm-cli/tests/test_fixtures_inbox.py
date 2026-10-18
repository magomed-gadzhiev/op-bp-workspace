"""Etap 7 Phase 4 — _inbox-http.yaml / _inbox-ssh.yaml writer with conflict detect."""
import tempfile
from pathlib import Path

import yaml

from pdm_cli.sandbox_mcp.fixtures_inbox import add_to_inbox


def _write_main(repo: Path, bp: str, kind: str, content: dict):
    d = repo / "processes" / bp / "fixtures"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{kind}-main.yaml").write_text(yaml.safe_dump(content))


def test_appends_to_inbox_http_yaml_when_empty():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "processes" / "bp1").mkdir(parents=True)
        out = add_to_inbox(
            repo, bp="bp1", kind="http",
            matcher={"method": "GET", "host": "x.local", "path": "/p"},
            response={"status": 200, "body": "ok"},
        )
        assert out["written_to"].endswith("_inbox-http.yaml")
        assert out["conflict"] is None
        loaded = yaml.safe_load(Path(out["written_to"]).read_text())
        assert loaded["matchers"][0]["request"]["path"] == "/p"


def test_detects_exact_conflict_in_main():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _write_main(repo, "bp1", "http", {"matchers": [{
            "request": {"method": "GET", "host": "x.local", "path": "/p"},
            "response": {"status": 200}
        }]})
        out = add_to_inbox(
            repo, bp="bp1", kind="http",
            matcher={"method": "GET", "host": "x.local", "path": "/p"},
            response={"status": 200, "body": "ok"},
        )
        assert out["conflict"] is not None
        assert out["conflict"]["kind"] == "exact_match_exists"


def test_detects_conflict_within_inbox():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "processes" / "b").mkdir(parents=True)
        add_to_inbox(repo, bp="b", kind="http",
                     matcher={"method": "POST", "host": "h", "path": "/q"},
                     response={"status": 201})
        out = add_to_inbox(repo, bp="b", kind="http",
                           matcher={"method": "POST", "host": "h", "path": "/q"},
                           response={"status": 201})
        assert out["conflict"] is not None
