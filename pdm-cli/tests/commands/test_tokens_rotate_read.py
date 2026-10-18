"""`pdm tokens rotate-read --env=...` calls internal endpoint and writes secret."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def repo(tmp_path, httpserver):
    (tmp_path / "pdm.config.yaml").write_text(
        f"endpoints:\n  prod: {httpserver.url_for('')}\n  sandbox: http://sb.local\n",
        encoding="utf-8",
    )
    (tmp_path / ".pdm").mkdir()
    (tmp_path / ".pdm" / "secrets.yaml").write_text(
        "api_key_prod: w\napi_key_sandbox: w\n",
        encoding="utf-8",
    )
    return tmp_path


def test_rotate_read_writes_to_secrets(repo, httpserver):
    httpserver.expect_request(
        "/api/internal/tokens/create-readonly/", method="POST",
    ).respond_with_json({"username": "pdm-mcp-read-prod", "token": "X" * 40})

    env = os.environ.copy()
    env["PDM_INTERNAL_API_TOKEN"] = "internal-token"
    r = subprocess.run(
        [sys.executable, "-m", "pdm_cli", "tokens", "rotate-read", "--env=prod"],
        cwd=str(repo), capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    secrets = (repo / ".pdm" / "secrets.yaml").read_text(encoding="utf-8")
    assert "read_api_key_prod:" in secrets
    assert "X" * 40 in secrets
