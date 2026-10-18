"""Etap 7 Phase 4 — full sandbox stack E2E (gated PDM_E2E=1)."""
import os
import subprocess
import sys
import json

import pytest

pytestmark = pytest.mark.e2e
ENABLED = os.environ.get("PDM_E2E") == "1"


@pytest.mark.skipif(not ENABLED, reason="set PDM_E2E=1")
def test_sandbox_mcp_serve_starts_and_lists_tools():
    """Start `pdm sandbox-mcp serve`, send list_tools, expect 6 tools."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "pdm_cli", "sandbox-mcp", "serve",
         "--skip-version-check"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    try:
        req_init = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05",
                       "capabilities": {},
                       "clientInfo": {"name": "e2e", "version": "0"}},
        }) + "\n"
        proc.stdin.write(req_init); proc.stdin.flush()
        proc.stdout.readline()
        req_init_done = json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized",
            "params": {},
        }) + "\n"
        proc.stdin.write(req_init_done); proc.stdin.flush()
        req_list = json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list",
            "params": {},
        }) + "\n"
        proc.stdin.write(req_list); proc.stdin.flush()
        line = proc.stdout.readline()
        data = json.loads(line)
        names = {t["name"] for t in data["result"]["tools"]}
        assert names == {
            "sandbox.run_test", "sandbox.run_step", "sandbox.inspect_state",
            "sandbox.list_egress", "sandbox.add_fixture",
            "sandbox.replay_with_override",
        }
    finally:
        proc.terminate()
        proc.wait(timeout=5)
