"""Config exposes read_api_key(env) loaded from .pdm/secrets.yaml flat format."""

from pathlib import Path

import pytest

from pdm_cli.config import ConfigError, load_config


def _write_config(tmp_path: Path, secrets: str) -> Path:
    (tmp_path / "pdm.config.yaml").write_text(
        "endpoints:\n  prod: http://prod.local\n  sandbox: http://sandbox.local\n",
        encoding="utf-8",
    )
    (tmp_path / ".pdm").mkdir(exist_ok=True)
    (tmp_path / ".pdm" / "secrets.yaml").write_text(secrets, encoding="utf-8")
    return tmp_path


def test_read_api_key_from_secrets(tmp_path):
    _write_config(tmp_path, """
api_key_prod: write-key-prod
api_key_sandbox: write-key-sandbox
read_api_key_prod: read-key-prod
read_api_key_sandbox: read-key-sandbox
""")
    cfg = load_config(tmp_path)
    assert cfg.read_api_key("prod") == "read-key-prod"
    assert cfg.read_api_key("sandbox") == "read-key-sandbox"


def test_read_api_key_env_override(tmp_path, monkeypatch):
    _write_config(tmp_path, """
api_key_prod: w
read_api_key_prod: secrets-file
""")
    monkeypatch.setenv("PDM_READ_API_KEY_PROD", "env-override")
    cfg = load_config(tmp_path)
    assert cfg.read_api_key("prod") == "env-override"


def test_read_api_key_missing_raises(tmp_path):
    _write_config(tmp_path, """
api_key_prod: w
""")
    cfg = load_config(tmp_path)
    with pytest.raises(ConfigError) as exc:
        cfg.read_api_key("prod")
    assert "pdm tokens rotate-read" in str(exc.value)
