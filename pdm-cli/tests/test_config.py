from pathlib import Path

import pytest

from pdm_cli.config import Config, ConfigError, load_config


def _write_config(tmp_path: Path, body: str) -> None:
    (tmp_path / "pdm.config.yaml").write_text(body, encoding="utf-8")


def _write_secrets(tmp_path: Path, body: str) -> None:
    (tmp_path / ".pdm").mkdir(exist_ok=True)
    (tmp_path / ".pdm" / "secrets.yaml").write_text(body, encoding="utf-8")


def test_load_minimal_config(tmp_path):
    _write_config(tmp_path,
        "endpoints:\n"
        "  prod: https://prod.local\n"
        "  sandbox: https://sandbox.local\n"
    )
    _write_secrets(tmp_path,
        "api_key_prod: PROD-KEY\n"
        "api_key_sandbox: SANDBOX-KEY\n"
        "cli_bypass_secret: BYPASS\n"
    )
    cfg = load_config(tmp_path)
    assert cfg.endpoint("prod") == "https://prod.local"
    assert cfg.endpoint("sandbox") == "https://sandbox.local"
    assert cfg.api_key("prod") == "PROD-KEY"
    assert cfg.api_key("sandbox") == "SANDBOX-KEY"
    assert cfg.cli_bypass_secret == "BYPASS"


def test_endpoint_strips_trailing_slash(tmp_path):
    _write_config(tmp_path,
        "endpoints:\n"
        "  prod: https://prod.local/\n"
    )
    _write_secrets(tmp_path, "api_key_prod: K\n")
    cfg = load_config(tmp_path)
    assert cfg.endpoint("prod") == "https://prod.local"


def test_env_var_overrides_secrets_file(tmp_path, monkeypatch):
    _write_config(tmp_path, "endpoints:\n  prod: https://p\n")
    _write_secrets(tmp_path, "api_key_prod: FROM-FILE\n")
    monkeypatch.setenv("PDM_API_KEY_PROD", "FROM-ENV")
    cfg = load_config(tmp_path)
    assert cfg.api_key("prod") == "FROM-ENV"


def test_env_var_overrides_bypass_secret(tmp_path, monkeypatch):
    _write_config(tmp_path, "endpoints:\n  prod: https://p\n")
    _write_secrets(tmp_path,
        "api_key_prod: K\n"
        "cli_bypass_secret: FROM-FILE\n"
    )
    monkeypatch.setenv("PDM_CLI_BYPASS_SECRET", "FROM-ENV")
    cfg = load_config(tmp_path)
    assert cfg.cli_bypass_secret == "FROM-ENV"


def test_secrets_file_optional(tmp_path, monkeypatch):
    _write_config(tmp_path, "endpoints:\n  prod: https://p\n")
    monkeypatch.setenv("PDM_API_KEY_PROD", "K")
    cfg = load_config(tmp_path)
    assert cfg.api_key("prod") == "K"
    assert cfg.cli_bypass_secret == ""


def test_missing_config_raises(tmp_path):
    with pytest.raises(ConfigError, match="pdm.config.yaml not found"):
        load_config(tmp_path)


def test_missing_endpoints_section_raises(tmp_path):
    _write_config(tmp_path, "other_field: value\n")
    with pytest.raises(ConfigError, match="endpoints"):
        load_config(tmp_path)


def test_missing_endpoint_raises_on_access(tmp_path):
    _write_config(tmp_path, "endpoints:\n  prod: https://p\n")
    _write_secrets(tmp_path, "api_key_prod: K\n")
    cfg = load_config(tmp_path)
    with pytest.raises(ConfigError, match="endpoint 'sandbox'"):
        cfg.endpoint("sandbox")


def test_missing_api_key_raises_on_access(tmp_path):
    _write_config(tmp_path, "endpoints:\n  prod: https://p\n  sandbox: https://s\n")
    _write_secrets(tmp_path, "api_key_prod: K\n")
    cfg = load_config(tmp_path)
    with pytest.raises(ConfigError, match="API key for 'sandbox'"):
        cfg.api_key("sandbox")


def test_empty_endpoints_map_raises(tmp_path):
    _write_config(tmp_path, "endpoints:\n")
    with pytest.raises(ConfigError, match="endpoints"):
        load_config(tmp_path)


def test_env_keys_uppercased(tmp_path, monkeypatch):
    """env var name is PDM_API_KEY_<ENV uppercase>."""
    _write_config(tmp_path, "endpoints:\n  staging: https://s\n")
    monkeypatch.setenv("PDM_API_KEY_STAGING", "S-KEY")
    cfg = load_config(tmp_path)
    assert cfg.api_key("staging") == "S-KEY"


def test_config_sandbox_runner_defaults(tmp_path, monkeypatch):
    """`pdm test` runner endpoints have sensible defaults when omitted."""
    _write_config(tmp_path, "endpoints:\n  sandbox: https://s\n")
    monkeypatch.setenv("PDM_API_KEY_SANDBOX", "K")
    cfg = load_config(tmp_path)
    assert cfg.hoverfly_admin == "http://localhost:8888"
    assert cfg.ssh_replay_journal == "http://localhost:8889"
    assert cfg.sandbox_db_dsn.startswith("postgresql://")


def test_config_sandbox_runner_overrides(tmp_path, monkeypatch):
    """Top-level keys in pdm.config.yaml override defaults."""
    _write_config(
        tmp_path,
        "endpoints:\n"
        "  sandbox: https://s\n"
        "hoverfly_admin: http://hf:9000\n"
        "ssh_replay_journal: http://ssh:9001\n"
        "sandbox_db_dsn: postgresql://u:p@db:5432/sbx\n",
    )
    monkeypatch.setenv("PDM_API_KEY_SANDBOX", "K")
    cfg = load_config(tmp_path)
    assert cfg.hoverfly_admin == "http://hf:9000"
    assert cfg.ssh_replay_journal == "http://ssh:9001"
    assert cfg.sandbox_db_dsn == "postgresql://u:p@db:5432/sbx"


def test_load_ignores_leftover_n8n_section(tmp_path, monkeypatch):
    """A leftover `n8n:` section from older configs is ignored (n8n removed)."""
    _write_config(
        tmp_path,
        "endpoints:\n"
        "  prod: https://p\n"
        "n8n:\n"
        "  base_url: http://n8n\n"
        "  api_key_env: N8N_KEY\n",
    )
    monkeypatch.setenv("PDM_API_KEY_PROD", "k")
    monkeypatch.setenv("N8N_KEY", "nk")
    cfg = load_config(tmp_path)  # must not raise
    assert cfg.api_key("prod") == "k"
    assert not hasattr(cfg, "n8n")


def test_config_loads_egress_redaction_rules(tmp_path):
    (tmp_path / "pdm.config.yaml").write_text("""
endpoints:
  sandbox: http://sandbox.local
egress:
  http:
    redact:
      - regex: 'Bearer [A-Za-z0-9_-]+'
        replacement: 'Bearer <token>'
      - header: Authorization
        replacement: '<redacted>'
  ssh:
    redact:
      - regex: '--password[= ]+\\S+'
        replacement: '--password=<redacted>'
""", encoding="utf-8")
    cfg = load_config(tmp_path)
    assert len(cfg.egress_http_redact) == 2
    assert cfg.egress_http_redact[0].regex == r'Bearer [A-Za-z0-9_-]+'
    assert cfg.egress_ssh_redact[0].regex == r'--password[= ]+\S+'
