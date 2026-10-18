"""Configuration loader: pdm.config.yaml + .pdm/secrets.yaml + env vars.

Resolution order for secrets (highest priority first):
  1. PDM_API_KEY_<ENV>, PDM_CLI_BYPASS_SECRET environment variables
  2. .pdm/secrets.yaml file
  3. (no fallback — missing values raise ConfigError on access)
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML


class ConfigError(Exception):
    pass


@dataclass
class RedactRule:
    regex: str = ""
    header: str = ""
    jsonpath: str = ""
    replacement: str = ""


@dataclass
class Config:
    repo_root: Path
    _endpoints: dict[str, str] = field(default_factory=dict)
    _api_keys: dict[str, str] = field(default_factory=dict)
    _read_api_keys: dict[str, str] = field(default_factory=dict)
    cli_bypass_secret: str = ""
    egress_http_redact: list[RedactRule] = field(default_factory=list)
    egress_ssh_redact: list[RedactRule] = field(default_factory=list)
    # Sandbox runner endpoints (overridable via top-level keys in
    # pdm.config.yaml: `hoverfly_admin`, `ssh_replay_journal`,
    # `sandbox_db_dsn`). Defaults match docker-compose.sandbox.yml.
    hoverfly_admin: str = "http://localhost:8888"
    ssh_replay_journal: str = "http://localhost:8889"
    sandbox_db_dsn: str = (
        "postgresql://pdm:sandbox@localhost:5432/pdm_sandbox_db"
    )

    def endpoint(self, name: str) -> str:
        url = self._endpoints.get(name)
        if not url:
            raise ConfigError(
                f"endpoint '{name}' not configured in pdm.config.yaml"
            )
        return url.rstrip("/")

    def api_key(self, env_name: str) -> str:
        key = self._api_keys.get(env_name)
        if not key:
            raise ConfigError(
                f"API key for '{env_name}' not configured "
                f"(set PDM_API_KEY_{env_name.upper()} env var "
                f"or .pdm/secrets.yaml:api_key_{env_name})"
            )
        return key

    def read_api_key(self, env_name: str) -> str:
        key = self._read_api_keys.get(env_name)
        if not key:
            raise ConfigError(
                f"read_api_key_{env_name} not configured "
                f"(set PDM_READ_API_KEY_{env_name.upper()} env var or run: "
                f"pdm tokens rotate-read)"
            )
        return key


def load_config(repo_root: Path) -> Config:
    repo_root = Path(repo_root)
    cfg_path = repo_root / "pdm.config.yaml"
    if not cfg_path.is_file():
        raise ConfigError(f"pdm.config.yaml not found at {cfg_path}")

    y = YAML(typ="safe")
    with cfg_path.open("r", encoding="utf-8") as f:
        cfg_data = y.load(f) or {}

    endpoints = cfg_data.get("endpoints", {}) or {}
    if not endpoints:
        raise ConfigError("pdm.config.yaml: 'endpoints' section is required")

    secrets_path = repo_root / ".pdm" / "secrets.yaml"
    secrets: dict = {}
    if secrets_path.is_file():
        with secrets_path.open("r", encoding="utf-8") as f:
            secrets = y.load(f) or {}

    api_keys: dict[str, str] = {}
    for env in endpoints.keys():
        env_var = f"PDM_API_KEY_{env.upper()}"
        secret_key = f"api_key_{env}"
        api_keys[env] = os.environ.get(env_var) or secrets.get(secret_key, "")

    read_api_keys: dict[str, str] = {}
    for env in endpoints.keys():
        env_var = f"PDM_READ_API_KEY_{env.upper()}"
        secret_key = f"read_api_key_{env}"
        read_api_keys[env] = (
            os.environ.get(env_var) or secrets.get(secret_key, "")
        )

    bypass = (
        os.environ.get("PDM_CLI_BYPASS_SECRET")
        or secrets.get("cli_bypass_secret", "")
    )

    egress = cfg_data.get("egress", {}) or {}
    http_redact = [
        RedactRule(**r) for r in (egress.get("http", {}) or {}).get("redact", []) or []
    ]
    ssh_redact = [
        RedactRule(**r) for r in (egress.get("ssh", {}) or {}).get("redact", []) or []
    ]

    # Backwards tolerance: a leftover `n8n:` section from older configs is
    # ignored silently (n8n integration has been removed from the OP stack).
    if "n8n" in cfg_data:
        print(
            "pdm.config.yaml: ignoring obsolete 'n8n:' section "
            "(n8n integration removed)",
            file=sys.stderr,
        )

    defaults = Config(repo_root=repo_root)
    return Config(
        repo_root=repo_root,
        _endpoints=endpoints,
        _api_keys=api_keys,
        _read_api_keys=read_api_keys,
        cli_bypass_secret=bypass,
        egress_http_redact=http_redact,
        egress_ssh_redact=ssh_redact,
        hoverfly_admin=(
            cfg_data.get("hoverfly_admin") or defaults.hoverfly_admin
        ),
        ssh_replay_journal=(
            cfg_data.get("ssh_replay_journal") or defaults.ssh_replay_journal
        ),
        sandbox_db_dsn=(
            cfg_data.get("sandbox_db_dsn") or defaults.sandbox_db_dsn
        ),
    )
