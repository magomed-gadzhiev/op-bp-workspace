"""ssh-replay override priority test (server-side unit, doesn't need real SSH).

The server module is import-safe (paramiko is only used inside main() which
is gated by `if __name__ == "__main__"`).
"""
import importlib
import os
import sys

import yaml


def _reload_server(override_dir):
    os.environ["SSH_REPLAY_OVERRIDE_DIR"] = str(override_dir)
    here = os.path.dirname(__file__)
    if here not in sys.path:
        sys.path.insert(0, here)
    if "server" in sys.modules:
        import server  # type: ignore
        importlib.reload(server)
    else:
        import server  # type: ignore  # noqa: F401
    return sys.modules["server"]


def test_override_matchers_loaded_when_dir_has_yaml(tmp_path):
    d = tmp_path
    (d / "replay-run1.yaml").write_text(yaml.safe_dump({
        "matchers": [{"request": {"host": "h", "user": "u",
                                  "command_matches": "cmd1"},
                      "response": {"stdout": "ok", "exit_code": 0}}]
    }))
    srv = _reload_server(d)
    matchers = srv._load_override_matchers()
    assert len(matchers) == 1
    assert matchers[0]["request"]["host"] == "h"


def test_corrupt_yaml_is_skipped(tmp_path):
    (tmp_path / "bad.yaml").write_text("not: a: yaml: [")
    srv = _reload_server(tmp_path)
    assert srv._load_override_matchers() == []


def test_empty_dir_returns_empty(tmp_path):
    srv = _reload_server(tmp_path)
    assert srv._load_override_matchers() == []


def test_file_deletion_seen_on_next_call(tmp_path):
    f = tmp_path / "replay-r1.yaml"
    f.write_text(yaml.safe_dump({
        "matchers": [{"request": {"host": "h", "user": "u",
                                  "command_matches": "x"},
                      "response": {}}]
    }))
    srv = _reload_server(tmp_path)
    assert len(srv._load_override_matchers()) == 1
    f.unlink()
    assert len(srv._load_override_matchers()) == 0
