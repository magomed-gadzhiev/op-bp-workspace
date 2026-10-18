import json
import os
import socket
import threading
import time
from pathlib import Path

import paramiko
import pytest


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _spawn_target_server(port, host_key, response_text="hello from target\n"):
    """Tiny SSH server that responds to any exec with response_text."""
    def serve():
        # The listening socket must be closed on every exit path; leaving it open
        # leaks an fd whose ResourceWarning surfaces (misattributed) in a later
        # test's GC — the noisy "flaky SSH teardown" from roadmap G7 (E17).
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
        sock.settimeout(15)
        try:
            try:
                c, _ = sock.accept()
            except Exception:
                return
            t = paramiko.Transport(c)
            t.add_server_key(host_key)
            class S(paramiko.ServerInterface):
                def check_auth_password(self, u, p): return paramiko.AUTH_SUCCESSFUL
                def check_auth_publickey(self, u, k): return paramiko.AUTH_SUCCESSFUL
                def get_allowed_auths(self, u): return "password,publickey"
                def check_channel_request(self, k, c): return paramiko.OPEN_SUCCEEDED if k == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
                def check_channel_exec_request(self, ch, cmd):
                    threading.Thread(target=self._reply, args=(ch,), daemon=True).start()
                    return True
                def _reply(self, ch):
                    ch.sendall(response_text.encode())
                    ch.send_exit_status(0)
                    time.sleep(0.05)
                    ch.close()
            t.start_server(server=S())
            ch = t.accept(10)
            time.sleep(0.3)
            t.close()
        finally:
            sock.close()
    th = threading.Thread(target=serve, daemon=True)
    th.start()
    return th


def test_bastion_forwards_and_captures(tmp_path):
    host_key = paramiko.RSAKey.generate(2048)
    host_key_path = tmp_path / "host"
    host_key.write_private_key_file(str(host_key_path))

    target_port = _free_port()
    _spawn_target_server(target_port, host_key)

    bastion_port = _free_port()
    capture_file = tmp_path / "ssh-capture.jsonl"
    os.environ.update({
        "SSH_HOST_KEY": str(host_key_path),
        "SSH_PORT": str(bastion_port),
        "BASTION_BP_SLUG": "payroll",
        "BASTION_TARGET_HOST": "127.0.0.1",
        "BASTION_TARGET_PORT": str(target_port),
        "BASTION_TARGET_USER": "anyone",
        "BASTION_FORWARD_KEY": "/nonexistent",
        "BASTION_FORWARD_PASSWORD": "anypass",
        "BASTION_CAPTURE_FILE": str(capture_file),
        "BASTION_REDACT_REGEX": '["--password[= ]+\\\\S+"]',
    })

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bastion", Path(__file__).parents[1] / "sandbox" / "ssh-bastion" / "bastion.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    threading.Thread(target=mod.main, daemon=True).start()
    time.sleep(0.5)

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect("127.0.0.1", port=bastion_port, username="deployer", password="x",
                look_for_keys=False, allow_agent=False, timeout=5)
    _, stdout, _ = cli.exec_command("deploy --password=topsecret")
    out = stdout.read().decode()
    code = stdout.channel.recv_exit_status()
    assert out.startswith("hello from target")
    assert code == 0

    time.sleep(0.2)
    actual_capture = tmp_path / "payroll" / "ssh-capture.jsonl"
    line = actual_capture.read_text(encoding="utf-8").strip().splitlines()[-1]
    rec = json.loads(line)
    assert "topsecret" not in rec["command"]
    assert "<redacted>" in rec["command"]
    assert rec["bp"] == "payroll"


def test_bastion_cfg_requires_bp_slug(monkeypatch):
    from tools_pdm_sandbox_ssh_bastion_compat import _cfg
    monkeypatch.delenv("BASTION_BP_SLUG", raising=False)
    monkeypatch.setenv("BASTION_TARGET_HOST", "h")
    monkeypatch.setenv("BASTION_TARGET_USER", "u")
    monkeypatch.setenv("BASTION_FORWARD_KEY", "/tmp/x")
    monkeypatch.setenv("BASTION_CAPTURE_FILE", "/captures/ssh-capture.jsonl")
    with pytest.raises(SystemExit) as exc:
        _cfg()
    assert exc.value.code == 2


def test_bastion_capture_file_includes_bp_subdir(monkeypatch, tmp_path):
    from tools_pdm_sandbox_ssh_bastion_compat import _cfg
    monkeypatch.setenv("BASTION_BP_SLUG", "payroll")
    monkeypatch.setenv("BASTION_TARGET_HOST", "h")
    monkeypatch.setenv("BASTION_TARGET_USER", "u")
    monkeypatch.setenv("BASTION_FORWARD_KEY", "/tmp/x")
    monkeypatch.setenv("BASTION_CAPTURE_FILE", str(tmp_path / "ssh-capture.jsonl"))
    cfg = _cfg()
    assert cfg["bp_slug"] == "payroll"
    assert str(cfg["capture_file"]).replace("\\", "/").endswith("/payroll/ssh-capture.jsonl")
