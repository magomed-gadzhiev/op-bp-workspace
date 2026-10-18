"""When read_api_key_<env> is missing, pdm mcp serve exits with rotate hint."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "pdm.config.yaml").write_text(
        "endpoints:\n  prod: http://prod.local\n  sandbox: http://sandbox.local\n",
        encoding="utf-8",
    )
    (tmp_path / ".pdm").mkdir()
    (tmp_path / ".pdm" / "secrets.yaml").write_text(
        "api_key_prod: w\napi_key_sandbox: w\n",
        encoding="utf-8",
    )
    return tmp_path


def test_serve_without_read_key_exits_with_hint(repo, monkeypatch):
    monkeypatch.delenv("PDM_READ_API_KEY_PROD", raising=False)
    # Simulate running from inside the repo
    r = subprocess.run(
        [sys.executable, "-m", "pdm_cli", "mcp", "serve", "--env=prod"],
        capture_output=True, text=True, cwd=str(repo),
    )
    assert r.returncode != 0
    assert "pdm tokens rotate-read" in r.stderr
