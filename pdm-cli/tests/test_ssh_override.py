"""Etap 7 Phase 3 — ssh-replay override-dir writer (client side)."""
import tempfile
from pathlib import Path

import yaml

from pdm_cli.sandbox_mcp.ssh_override import SshOverrideContext


def test_inject_writes_yaml_then_unlink_on_exit():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        run_id = "abc123"
        with SshOverrideContext(d, run_id) as ctx:
            ctx.inject([{"request": {"host": "h.local",
                                     "command_matches": "deploy.*"},
                         "response": {"stdout": "ok", "exit_code": 0}}])
            assert (d / f"replay-{run_id}.yaml").exists()
            loaded = yaml.safe_load((d / f"replay-{run_id}.yaml").read_text())
            assert loaded["matchers"][0]["request"]["host"] == "h.local"
        assert not (d / f"replay-{run_id}.yaml").exists()


def test_inject_overwrites_previous_in_same_context():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        with SshOverrideContext(d, "r1") as ctx:
            ctx.inject([{"request": {"host": "a"},
                         "response": {"exit_code": 0}}])
            ctx.inject([{"request": {"host": "b"},
                         "response": {"exit_code": 1}}])
            loaded = yaml.safe_load((d / "replay-r1.yaml").read_text())
            assert loaded["matchers"][0]["request"]["host"] == "b"


def test_unlink_failure_does_not_raise():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        with SshOverrideContext(d, "r2") as ctx:
            ctx.inject([{"request": {}, "response": {}}])
            (d / "replay-r2.yaml").unlink()
        # context exit should not raise even though file already gone
