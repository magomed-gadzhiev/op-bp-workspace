"""End-to-end: pdm mcp serve sandbox returns merged egress for a fresh pdm-test run.

Marked @pytest.mark.e2e — skipped by default. Run via:
  PDM_E2E=1 PDM_E2E_REPO=<repo path> pytest tests/e2e/test_mcp_e2e.py -v -m e2e

Requires:
  - Sandbox stack up: docker compose -f docker-compose.full.yml -f \
      tools/pdm-cli/sandbox/docker-compose.sandbox.yml up -d
  - A sample BP with a happy-path case wired in the test repo
  - pdm-cli[mcp] installed in env
"""

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_mcp_get_run_details_merges_journal_and_api():
    if not os.environ.get("PDM_E2E"):
        pytest.skip("set PDM_E2E=1 to run")

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        pytest.skip("mcp SDK not installed (pip install pdm-cli[mcp])")

    repo = Path(os.environ.get("PDM_E2E_REPO", ".")).resolve()

    # Step 1: pdm test --keep produces a run_id and a journal under .pdm/runs/<id>/
    subprocess.run(
        ["pdm", "test", "--bp", "sample-bp", "--case", "happy-path", "--keep"],
        cwd=str(repo), check=True,
    )
    last_run = json.loads((repo / ".pdm" / "last-run.json").read_text())
    run_id = int(last_run["cases"][0]["run_id"])

    # Step 2: Spawn `pdm mcp serve --env=sandbox` as subprocess via stdio MCP client
    async def _call():
        params = StdioServerParameters(
            command="pdm",
            args=["mcp", "serve", "--env=sandbox"],
            cwd=str(repo),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                tool_names = {t.name for t in tools.tools}
                assert "get_run_details" in tool_names
                result = await session.call_tool(
                    "get_run_details", {"run_id": run_id},
                )
                # MCP returns ContentBlock objects; extract JSON-serialized text
                content_block = result.content[0]
                text = getattr(content_block, "text", None) or str(content_block)
                return json.loads(text)

    details = asyncio.run(_call())
    assert details["run_id"] == run_id
    assert details["egress_source"] == "merged"
    assert len(details["egress"]["http"]) >= 1
    for e in details["egress"]["http"]:
        assert e.get("source") in ("pdm-script", "pdm-ssh", "unknown")
