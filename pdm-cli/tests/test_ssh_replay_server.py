"""Test SSH replay server in-process (no Docker), using paramiko as client."""
import json
import os
import socket
import threading
import time
import urllib.request
from pathlib import Path

import paramiko
import pytest


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def replay_server(tmp_path):
    host_key = paramiko.RSAKey.generate(2048)
    host_key_path = tmp_path / "host_rsa_key"
    host_key.write_private_key_file(str(host_key_path))

    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "ssh-test.yaml").write_text("""
name: test
matchers:
  - request:
      host: deploy.local
      user: deployer
      command_matches: 'deploy --v (?P<v>\\S+)'
    response:
      stdout: "OK {{v}}\\n"
      exit_code: 0
""", encoding="utf-8")

    port = _free_port()
    journal_port = _free_port()
    control_port = _free_port()

    env = {
        "SSH_HOST_KEY": str(host_key_path),
        "SSH_FIXTURES_DIR": str(fixtures_dir),
        "SSH_PORT": str(port),
        "SSH_TARGET_HOST": "deploy.local",
        "SSH_JOURNAL_PORT": str(journal_port),
        "SSH_REPLAY_CONTROL_PORT": str(control_port),
        "SSH_REPLAY_OVERRIDE_DIR": str(tmp_path / "ssh-overrides"),
    }
    old_env = {k: os.environ.get(k) for k in env}
    os.environ.update(env)

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ssh_replay_server",
        Path(__file__).parents[1] / "sandbox" / "ssh-replay" / "server.py",
    )
    server_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_mod)

    t = threading.Thread(target=server_mod.main, daemon=True)
    t.start()
    time.sleep(0.5)
    yield (port, journal_port, control_port, Path(env["SSH_REPLAY_OVERRIDE_DIR"]))

    for k, v in old_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_ssh_replay_matches_command(replay_server):
    port, _, _, _ = replay_server
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("127.0.0.1", port=port, username="deployer", password="any", look_for_keys=False, allow_agent=False)
    stdin, stdout, stderr = client.exec_command("deploy --v 1.2.3")
    assert stdout.read().decode() == "OK 1.2.3\n"
    assert stdout.channel.recv_exit_status() == 0


def test_ssh_replay_no_match_returns_127(replay_server):
    port, _, _, _ = replay_server
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("127.0.0.1", port=port, username="deployer", password="any", look_for_keys=False, allow_agent=False)
    stdin, stdout, stderr = client.exec_command("rm -rf /")
    assert stdout.channel.recv_exit_status() == 127
    assert b"no fixture" in stderr.read()


def _journal_get(journal_port: int):
    with urllib.request.urlopen(f"http://127.0.0.1:{journal_port}/journal") as resp:
        assert resp.status == 200
        return json.loads(resp.read().decode("utf-8"))


def _journal_delete(journal_port: int) -> int:
    req = urllib.request.Request(f"http://127.0.0.1:{journal_port}/journal", method="DELETE")
    with urllib.request.urlopen(req) as resp:
        return resp.status


def test_journal_records_exec_requests(replay_server):
    """When a client makes an exec request, it appears in /journal GET."""
    port, journal_port, _, _ = replay_server
    # Clear any leftover entries (server is module-global)
    _journal_delete(journal_port)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("127.0.0.1", port=port, username="deployer", password="any",
                   look_for_keys=False, allow_agent=False)
    stdin, stdout, stderr = client.exec_command("deploy --v 9.9.9")
    assert stdout.channel.recv_exit_status() == 0
    client.close()

    # Give the server a moment to record after channel close
    time.sleep(0.2)

    entries = _journal_get(journal_port)
    assert isinstance(entries, list)
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry["command"] == "deploy --v 9.9.9"
    assert isinstance(entry["exit_code"], int)
    assert entry["exit_code"] == 0
    assert entry["host"]  # set
    assert entry["user"] == "deployer"
    assert entry["matched_fixture"] == "test"
    assert "ts" in entry


def test_journal_records_unmatched_with_null_fixture(replay_server):
    """Unmatched exec is journaled too, with matched_fixture=None and exit_code=127."""
    port, journal_port, _, _ = replay_server
    _journal_delete(journal_port)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("127.0.0.1", port=port, username="deployer", password="any",
                   look_for_keys=False, allow_agent=False)
    stdin, stdout, stderr = client.exec_command("nonexistent --cmd")
    assert stdout.channel.recv_exit_status() == 127
    client.close()

    time.sleep(0.2)

    entries = _journal_get(journal_port)
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry["command"] == "nonexistent --cmd"
    assert entry["exit_code"] == 127
    assert entry["matched_fixture"] is None


def test_journal_delete_clears_entries(replay_server):
    """DELETE /journal empties the journal and returns 204."""
    port, journal_port, _, _ = replay_server
    _journal_delete(journal_port)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("127.0.0.1", port=port, username="deployer", password="any",
                   look_for_keys=False, allow_agent=False)
    stdin, stdout, stderr = client.exec_command("deploy --v 1.0.0")
    stdout.channel.recv_exit_status()
    client.close()
    time.sleep(0.2)

    entries = _journal_get(journal_port)
    assert len(entries) >= 1

    status = _journal_delete(journal_port)
    assert status == 204

    entries_after = _journal_get(journal_port)
    assert entries_after == []


def test_control_reload_endpoint_counts_override_matchers(replay_server):
    """POST /_internal/reload validates override files and returns matcher count."""
    _, _, control_port, override_dir = replay_server
    override_dir.mkdir(parents=True, exist_ok=True)
    (override_dir / "replay-r1.yaml").write_text("""
matchers:
  - request:
      host: deploy.local
      user: deployer
      command_matches: '^whoami$'
    response:
      stdout: "deployer\\n"
      exit_code: 0
""", encoding="utf-8")

    req = urllib.request.Request(
        f"http://127.0.0.1:{control_port}/_internal/reload",
        method="POST",
        data=b"",
    )
    with urllib.request.urlopen(req) as resp:
        body = resp.read().decode("utf-8")
        status = resp.status
    assert status == 200
    assert "reloaded matchers=1" in body
