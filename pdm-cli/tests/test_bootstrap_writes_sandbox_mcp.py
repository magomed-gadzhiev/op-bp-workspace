"""Etap 7 Phase 4 — bootstrap writes third MCP entry for pdm-sandbox.

The Etap 6 bootstrap copied a `mcp_config.json` template into
`.claude/mcp.json`. Etap 7 renames the read-only sandbox entry from
`pdm-sandbox` to `pdm-sandbox-readonly` and introduces a new
interactive `pdm-sandbox` (sandbox-mcp serve) entry.
"""
import json

import respx
from click.testing import CliRunner

from pdm_cli.cli import main


PROD = "https://prod.local"
SB = "https://sandbox.local"


@respx.mock
def test_mcp_json_contains_three_servers_after_etap7(tmp_path):
    respx.get(f"{PROD}/api/business-processes/").respond(json=[])

    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "K",
        "--sandbox-url", SB, "--api-key-sandbox", "S",
    ], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output

    mcp_json_path = tmp_path / ".claude" / "mcp.json"
    assert mcp_json_path.is_file()
    data = json.loads(mcp_json_path.read_text(encoding="utf-8"))
    servers = data["mcpServers"]
    assert "pdm-prod" in servers
    assert "pdm-sandbox-readonly" in servers
    assert "pdm-sandbox" in servers
    assert servers["pdm-sandbox"]["args"] == ["sandbox-mcp", "serve"]
    # Sanity: the read-only entry still points at the read-only MCP.
    assert servers["pdm-sandbox-readonly"]["args"] == ["mcp", "serve", "--env=sandbox"]
