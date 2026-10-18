"""Replay-only SSH server (Tier 1 non-interactive exec).

Loads YAML fixtures from /fixtures/ (mounted from client-project's
processes/*/fixtures/ssh-*.yaml). On exec request, looks up a matcher
by (host, user, command-regex) and returns the recorded response.

Accepts any authentication (sandbox-only). Host key persists across restarts.
"""
from __future__ import annotations
import json
import logging
import os
import socket
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import paramiko

sys.path.insert(0, "/work/src")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pdm_cli.fixtures.ssh import SshFixture, load_ssh_fixture, match_ssh_request
from envparse import parse_pdm_envprefix

# Etap 7 Phase 3 — ssh-replay override-dir support.
# sandbox-mcp writes per-run YAML files (matchers schema identical to main
# fixtures) into SSH_REPLAY_OVERRIDE_DIR; we re-glob the dir on every SSH
# connection and try override matchers before the main fixtures.
SSH_REPLAY_OVERRIDE_DIR = os.environ.get(
    "SSH_REPLAY_OVERRIDE_DIR", "/var/sandbox/ssh-overrides"
)


def _load_override_matchers() -> list[dict]:
    """Re-glob the override-dir each call (cheap; <10ms for N≈20 fixtures).

    Returns raw matcher dicts. Corrupt YAML files are skipped with a stderr
    warning so a bad override never crashes the server.
    """
    p = Path(SSH_REPLAY_OVERRIDE_DIR)
    if not p.is_dir():
        return []
    out: list[dict] = []
    # Lazy import: pyyaml is sufficient for the override format (plain dicts).
    import yaml as _yaml
    for fp in sorted(p.glob("*.yaml")):
        try:
            data = _yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
            for m in (data.get("matchers") or []):
                out.append(m)
        except Exception as e:  # noqa: BLE001
            print(f"[ssh-replay] skipping corrupt override {fp.name}: {e}",
                  file=sys.stderr)
    return out


def _override_fixture() -> Optional[SshFixture]:
    """Build an in-memory SshFixture from the override-dir, or None if empty."""
    matchers = _load_override_matchers()
    if not matchers:
        return None
    try:
        return SshFixture.model_validate({
            "name": "__override__",
            "matchers": matchers,
        })
    except Exception as e:  # noqa: BLE001
        print(f"[ssh-replay] override matchers failed validation: {e}",
              file=sys.stderr)
        return None

LOG = logging.getLogger("ssh-replay")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

HOST_KEY_PATH = os.environ.get("SSH_HOST_KEY", "/keys/host_rsa_key")
FIXTURES_DIR = Path(os.environ.get("SSH_FIXTURES_DIR", "/fixtures"))
PORT = int(os.environ.get("SSH_PORT", "22"))
TARGET_HOST_HINT = os.environ.get("SSH_TARGET_HOST", "deploy.local")
JOURNAL_PORT = int(os.environ.get("SSH_JOURNAL_PORT", "8889"))
BP_SLUG = os.environ.get("REPLAY_BP_SLUG") or os.environ.get("BASTION_BP_SLUG")


# ---------------------------------------------------------------------------
# In-memory journal for side-effect assertions in `pdm test`.
# ---------------------------------------------------------------------------
_JOURNAL: list[dict] = []
_JOURNAL_LOCK = threading.Lock()


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


def record_exec(host: str, user: str, command: str,
                matched_fixture: Optional[str], exit_code: int,
                run_id: Optional[str] = None, source: Optional[str] = None,
                stdout: str = "", stderr: str = "",
                duration_ms: int = 0) -> None:
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with _JOURNAL_LOCK:
        _JOURNAL.append({
            "host": host,
            "user": user,
            "command": command,
            "matched_fixture": matched_fixture,
            "exit_code": exit_code,
            "run_id": run_id,
            "source": source,
            "ts": ts,
        })
    _post_to_pdm({
        "bp_slug": BP_SLUG,
        "bp_run_id": int(run_id) if run_id and run_id.isdigit() else None,
        "host": host,
        "user": user,
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "started_at": ts,
        "source": source or "pdm-ssh",
    })


class JournalHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/journal":
            with _JOURNAL_LOCK:
                body = json.dumps(list(_JOURNAL)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_DELETE(self):  # noqa: N802
        if self.path == "/journal":
            with _JOURNAL_LOCK:
                _JOURNAL.clear()
            self.send_response(204)
            self.end_headers()
            return
        self.send_error(404)

    def log_message(self, fmt, *args):  # silence access log
        return


def start_journal_server(port: int) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("0.0.0.0", port), JournalHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    LOG.info("Journal HTTP listening on :%d", port)
    return srv


# ---------------------------------------------------------------------------
# Etap 8 Phase 2 — control HTTP endpoint for hot-reload.
#
# Override fixtures are already re-read on each SSH connection (cheap re-glob
# in `_load_override_matchers`), so there is no in-memory cache to invalidate.
# Nonetheless we expose `POST /_internal/reload` as an explicit control
# contract used by the inotify watcher (watcher.py): each disk event triggers
# a POST, the handler re-runs the loader to validate fixtures parse, and
# returns the matcher count. On parse failures the loader already logs to
# stderr and skips bad files — the endpoint never raises for that case.
# ---------------------------------------------------------------------------
CONTROL_PORT = int(os.environ.get("SSH_REPLAY_CONTROL_PORT", "2223"))


class _ControlHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        if self.path != "/_internal/reload":
            self.send_response(404)
            self.end_headers()
            return
        # Localhost-only — the listener already binds to 127.0.0.1 but we
        # double-check the peer address for defence-in-depth.
        peer = self.client_address[0]
        if peer not in ("127.0.0.1", "::1"):
            self.send_response(403)
            self.end_headers()
            return
        try:
            matchers = _load_override_matchers()
        except Exception as e:  # noqa: BLE001
            self.send_response(500)
            self.end_headers()
            try:
                self.wfile.write(f"reload failed: {e}".encode("utf-8"))
            except Exception:  # noqa: BLE001
                pass
            return
        body = f"reloaded matchers={len(matchers)}".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:  # noqa: BLE001
            pass

    def log_message(self, fmt, *args):  # silence access log
        return


def start_control_server(port: int = CONTROL_PORT) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), _ControlHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    LOG.info("Control HTTP listening on 127.0.0.1:%d", port)
    return srv


def load_fixtures() -> list[SshFixture]:
    fixtures: list[SshFixture] = []
    if not FIXTURES_DIR.is_dir():
        LOG.warning("Fixtures dir %s does not exist; replay will return 127 for all exec.", FIXTURES_DIR)
        return fixtures
    for yaml in FIXTURES_DIR.rglob("ssh-*.yaml"):
        try:
            fixtures.append(load_ssh_fixture(yaml))
            LOG.info("Loaded SSH fixture: %s", yaml)
        except Exception as e:
            LOG.error("Failed to load %s: %s", yaml, e)
    return fixtures


class ReplayServerIface(paramiko.ServerInterface):
    def __init__(self):
        self.exec_event = threading.Event()
        self.command: str = ""
        self.username: str = ""

    def check_auth_password(self, username, password):
        self.username = username
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_publickey(self, username, key):
        self.username = username
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return "password,publickey"

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel, command):
        self.command = command.decode("utf-8", errors="replace") if isinstance(command, (bytes, bytearray)) else command
        self.exec_event.set()
        return True


def _handle_session(client_sock, addr, host_key, fixtures):
    LOG.info("Connection from %s", addr)
    transport = paramiko.Transport(client_sock)
    transport.add_server_key(host_key)
    server = ReplayServerIface()
    try:
        transport.start_server(server=server)
    except paramiko.SSHException as e:
        LOG.error("SSH handshake failed: %s", e)
        return

    channel = transport.accept(10)
    if channel is None:
        LOG.warning("No channel established")
        transport.close()
        return

    server.exec_event.wait(10)
    if not server.command:
        channel.send_stderr("replay: no exec command received\n")
        channel.send_exit_status(127)
        record_exec(host=TARGET_HOST_HINT, user=server.username, command="",
                    matched_fixture=None, exit_code=127)
        channel.close()
        transport.close()
        return

    run_id, source, stripped_command = parse_pdm_envprefix(server.command)
    LOG.info("Exec from %s@%s (run_id=%s, source=%s): %s",
             server.username, TARGET_HOST_HINT, run_id, source, stripped_command)
    matched_name: Optional[str] = None
    final_exit_code = 127
    captured_stdout = ""
    captured_stderr = ""
    # Etap 7 Phase 3 — try override matchers first (per-run ephemeral fixtures
    # written by sandbox-mcp's SshOverrideContext into SSH_REPLAY_OVERRIDE_DIR).
    override_fix = _override_fixture()
    candidate_fixtures = ([override_fix] if override_fix is not None else []) + list(fixtures)
    for fix in candidate_fixtures:
        resp = match_ssh_request(fix, host=TARGET_HOST_HINT, user=server.username, command=stripped_command)
        if resp is not None:
            if resp.stdout:
                channel.sendall(resp.stdout.encode("utf-8"))
                captured_stdout = resp.stdout
            if resp.stderr:
                channel.send_stderr(resp.stderr)
                captured_stderr = resp.stderr
            channel.send_exit_status(resp.exit_code)
            matched_name = fix.name
            final_exit_code = resp.exit_code
            break
    else:
        msg = f"replay: no fixture for command: {stripped_command}\n"
        channel.send_stderr(msg)
        channel.send_exit_status(127)
        captured_stderr = msg

    record_exec(
        host=TARGET_HOST_HINT,
        user=server.username,
        command=stripped_command,
        matched_fixture=matched_name,
        exit_code=final_exit_code,
        run_id=run_id,
        source=source,
        stdout=captured_stdout,
        stderr=captured_stderr,
        duration_ms=0,
    )

    channel.close()
    transport.close()


def main():
    host_key = paramiko.RSAKey(filename=HOST_KEY_PATH)
    fixtures = load_fixtures()

    # Re-read JOURNAL_PORT at call time so tests that patch the env after import work.
    journal_port = int(os.environ.get("SSH_JOURNAL_PORT", str(JOURNAL_PORT)))
    start_journal_server(journal_port)
    # Etap 8 Phase 2 — control endpoint for inotify-driven hot-reload.
    control_port = int(os.environ.get("SSH_REPLAY_CONTROL_PORT", str(CONTROL_PORT)))
    start_control_server(control_port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", PORT))
    sock.listen(8)
    LOG.info("SSH replay listening on :%d (target hint=%s, fixtures=%d)", PORT, TARGET_HOST_HINT, len(fixtures))

    while True:
        client_sock, addr = sock.accept()
        threading.Thread(target=_handle_session, args=(client_sock, addr, host_key, fixtures),
                         daemon=True).start()


if __name__ == "__main__":
    main()
