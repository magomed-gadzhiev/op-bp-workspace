"""End-to-end smoke test.

Requires a running PDM stack and these env vars:
- PDM_TEST_BASE_URL  — URL to the PDM backend (e.g. http://pdm-backend:8000)
- PDM_TEST_API_KEY   — token authenticating as a superuser
- PDM_TEST_BYPASS_SECRET (optional) — bypass for read-only mode

To run from inside the pdm-cli-dev container:

    docker compose -f docker-compose.full.yml exec \
      -e PDM_TEST_BASE_URL=http://pdm-backend:8000 \
      -e PDM_TEST_API_KEY=<token> \
      pdm-cli-dev pytest -m e2e -v

Skipped by default — only runs when PDM_TEST_BASE_URL is set.
"""

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from pdm_cli.cli import main


pytestmark = pytest.mark.skipif(
    not os.environ.get("PDM_TEST_BASE_URL"),
    reason="set PDM_TEST_BASE_URL to enable e2e tests",
)


def _setup_repo(tmp_path):
    base_url = os.environ["PDM_TEST_BASE_URL"]
    api_key = os.environ["PDM_TEST_API_KEY"]
    bypass = os.environ.get("PDM_TEST_BYPASS_SECRET", "")

    runner = CliRunner()

    # Bootstrap (use same URL for prod and sandbox in Etap 1)
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", base_url, "--api-key", api_key,
        "--sandbox-url", base_url, "--api-key-sandbox", api_key,
    ], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output

    if bypass:
        secrets = tmp_path / ".pdm" / "secrets.yaml"
        text = secrets.read_text(encoding="utf-8").replace(
            'cli_bypass_secret: ""',
            f'cli_bypass_secret: "{bypass}"',
        )
        secrets.write_text(text, encoding="utf-8")

    return runner, tmp_path


@pytest.mark.e2e
def test_bootstrap_then_validate(tmp_path):
    runner, root = _setup_repo(tmp_path)
    result = runner.invoke(main, ["validate"], obj={"cwd": root})
    assert result.exit_code == 0, result.output


@pytest.mark.e2e
def test_diff_after_bootstrap_clean(tmp_path):
    """Right after bootstrap, local should match remote — no diffs."""
    runner, root = _setup_repo(tmp_path)
    result = runner.invoke(main, ["diff", "--against", "prod"], obj={"cwd": root})
    assert result.exit_code == 0, result.output
    # Either no processes (if PDM is empty) or no differences
    out_lower = result.output.lower()
    assert "no differences" in out_lower or "no processes" in out_lower


@pytest.mark.e2e
def test_push_to_sandbox_when_processes_exist(tmp_path):
    """If PDM has any processes, push them to sandbox should succeed (idempotent)."""
    runner, root = _setup_repo(tmp_path)
    proc_dir = root / "processes"
    if not proc_dir.exists() or not any(proc_dir.iterdir()):
        pytest.skip("No processes in test PDM — skipping push test")

    result = runner.invoke(main, ["push", "--to", "sandbox"], obj={"cwd": root})
    assert result.exit_code == 0, result.output
