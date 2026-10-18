"""SSH bastion: capture mode for Tier 1 non-interactive exec.

Accepts incoming SSH, forwards exec to a real target via paramiko client,
relays stdout/stderr/exit_code back to caller, and logs the (redacted) trio
to /captures/ssh-capture.jsonl as JSON lines.
"""
from __future__ import annotations
import json
import logging
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from envparse import parse_pdm_envprefix  # noqa: E402

LOG = logging.getLogger("ssh-bastion")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _post_to_pdm(payload: dict) -> None:
    """Best-effort POST to PDM internal egress-logs endpoint. Never raises."""
    url = os.environ.get("PDM_INTERNAL_API_URL")
    token = os.environ.get("PDM_INTERNAL_API_TOKEN")
    if not (url and token):
        return
    try:
        import requests  # local import: optional dep
        requests.post(
            url.rstrip("/") + "/api/internal/egress-logs/ssh/",
            json=payload,
            headers={"X-PDM-Internal-Token": token},
            timeout=2.0,
        )
    except Exception as e:  # noqa: BLE001
        LOG.warning("egress post failed: %s", e)


def _cfg():
    """Read configuration from environment at call time (allows test overrides)."""
    redact_raw = os.environ.get("BASTION_REDACT_REGEX", "[]")
    patterns = [re.compile(r) for r in json.loads(redact_raw)]
    bp_slug = os.environ.get("BASTION_BP_SLUG", "").strip()
    if not bp_slug:
        LOG.error("BASTION_BP_SLUG is required (per-BP capture isolation). Set it in compose env.")
        sys.exit(2)
    raw_capture = os.environ.get("BASTION_CAPTURE_FILE", "/captures/ssh-capture.jsonl")
    capture_path = Path(raw_capture)
    capture_file = capture_path.parent / bp_slug / capture_path.name
    return {
        "host_key": os.environ.get("SSH_HOST_KEY", "/keys/host_rsa_key"),
        "target_host": os.environ.get("BASTION_TARGET_HOST", ""),
        "target_port": int(os.environ.get("BASTION_TARGET_PORT", "22")),
        "target_user": os.environ.get("BASTION_TARGET_USER", ""),
        "forward_key": os.environ.get("BASTION_FORWARD_KEY", "/keys/forward_id_rsa"),
        "forward_password": os.environ.get("BASTION_FORWARD_PASSWORD", ""),
        "port": int(os.environ.get("SSH_PORT", "22")),
        "capture_file": capture_file,
        "bp_slug": bp_slug,
        "redact_patterns": patterns,
    }


def _redact(text: str, patterns) -> str:
    for r in patterns:
        text = r.sub("<redacted>", text)
    return text


def _log_capture(cfg, host, user, command, stdout, stderr, exit_code, duration_ms):
    capture_file = cfg["capture_file"]
    patterns = cfg["redact_patterns"]
    capture_file.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bp": cfg["bp_slug"],
        "host": host,
        "user": user,
        "command": _redact(command, patterns),
        "stdout": _redact(stdout, patterns),
        "stderr": _redact(stderr, patterns),
        "exit_code": exit_code,
        "duration_ms": duration_ms,
    }
    with capture_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


class BastionIface(paramiko.ServerInterface):
    def __init__(self):
        self.exec_event = threading.Event()
        self.command = ""
        self.username = ""

    def check_auth_password(self, username, password):
        self.username = username
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_publickey(self, username, key):
        self.username = username
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return "password,publickey"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel, command):
        self.command = command.decode("utf-8", errors="replace") if isinstance(command, (bytes, bytearray)) else command
        self.exec_event.set()
        return True


def _forward_exec(cfg, command: str) -> tuple[str, str, int]:
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    forward_key = cfg["forward_key"]
    pkey = paramiko.RSAKey.from_private_key_file(forward_key) if Path(forward_key).exists() else None
    password = cfg["forward_password"] if pkey is None else None
    cli.connect(cfg["target_host"], port=cfg["target_port"], username=cfg["target_user"], pkey=pkey,
                password=password, look_for_keys=False, allow_agent=False, timeout=10)
    stdin, stdout, stderr = cli.exec_command(command, timeout=60)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    cli.close()
    return out, err, code


def _handle(client_sock, addr, host_key):
    cfg = _cfg()
    transport = paramiko.Transport(client_sock)
    transport.add_server_key(host_key)
    iface = BastionIface()
    try:
        transport.start_server(server=iface)
    except paramiko.SSHException as e:
        LOG.error("Handshake failed: %s", e)
        return
    ch = transport.accept(10)
    if ch is None:
        transport.close()
        return
    iface.exec_event.wait(10)
    started = time.time()
    run_id, source, stripped_command = parse_pdm_envprefix(iface.command)
    # SECURITY: forward STRIPPED command to the real target. PDM_RUN_ID/PDM_SOURCE
    # markers stay on the bastion and must not leak to the downstream host.
    try:
        out, err, code = _forward_exec(cfg, stripped_command)
    except Exception as e:
        out, err, code = "", f"bastion: forward failed: {e}\n", 254
    duration_ms = int((time.time() - started) * 1000)
    _log_capture(cfg, cfg["target_host"], iface.username, stripped_command, out, err, code, duration_ms)
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))
    _post_to_pdm({
        "bp_run_id": int(run_id) if run_id and run_id.isdigit() else None,
        "host": cfg["target_host"],
        "user": iface.username,
        "command": stripped_command,
        "stdout": out,
        "stderr": err,
        "exit_code": code,
        "duration_ms": duration_ms,
        "started_at": started_at,
        "source": source or "pdm-ssh",
    })
    if out:
        ch.sendall(out.encode("utf-8"))
    if err:
        ch.send_stderr(err)
    ch.send_exit_status(code)
    ch.close()
    transport.close()


def main():
    cfg = _cfg()
    host_key = paramiko.RSAKey(filename=cfg["host_key"])
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", cfg["port"]))
    sock.listen(8)
    LOG.info("Bastion on :%d → %s@%s:%d, capture=%s",
             cfg["port"], cfg["target_user"], cfg["target_host"], cfg["target_port"], cfg["capture_file"])
    while True:
        c, a = sock.accept()
        threading.Thread(target=_handle, args=(c, a, host_key), daemon=True).start()


if __name__ == "__main__":
    main()
