"""FastMCP assembly for `pdm sandbox-mcp serve`.

Hard-coded sandbox-only — the server reads pdm.config.yaml's
`environments.sandbox` and refuses to start if it is absent.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import uuid
from pathlib import Path

import click

from .mutex import SandboxMutex

EXPECTED_API_MAJOR = "1"
_OWNER_ID = (
    os.environ.get("PDM_SANDBOX_OWNER_ID")
    or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
)

logger = logging.getLogger(__name__)


class SandboxConfigError(RuntimeError):
    pass


def _lock_conflict_result(body: dict) -> dict:
    retry_after = body.get("retry_after", 10)
    current_owner = body.get("current_owner")
    return {
        "status": "locked",
        "message": (
            "Another sandbox-mcp session is holding the override-run lock "
            f"(owner: {current_owner}). Retry in {retry_after} seconds, "
            "or terminate the other session."
        ),
        "retry_after": retry_after,
        "current_owner": current_owner,
    }


def _build_context(repo_root: Path) -> dict:
    from ..config import ConfigError, load_config
    from ..api_client import PdmApiClient
    cfg = load_config(repo_root)
    try:
        sandbox_endpoint = cfg.endpoint("sandbox")
    except Exception as e:
        raise SandboxConfigError(
            f"sandbox endpoint missing in pdm.config.yaml: {e}"
        )
    try:
        token = cfg.read_api_key("sandbox")
    except ConfigError as e:
        raise SandboxConfigError(str(e))
    api = PdmApiClient(base_url=sandbox_endpoint, api_key=token)
    sandbox_env = cfg.raw.get("environments", {}).get("sandbox", {})
    hoverfly_admin = sandbox_env.get("hoverfly_admin", "http://localhost:8888")
    ssh_replay_journal = sandbox_env.get("ssh_replay_journal", "http://localhost:8910")
    sandbox_db_dsn = sandbox_env.get("db_dsn", "")
    override_dir = repo_root / ".pdm" / "sandbox" / "ssh-overrides"
    return {
        "repo_root": repo_root,
        "api": api,
        "cfg": cfg,
        "hoverfly_admin": hoverfly_admin,
        "ssh_replay_journal": ssh_replay_journal,
        "sandbox_db_dsn": sandbox_db_dsn,
        "pdm_api_base": sandbox_endpoint,
        "pdm_api_key": token,
        "ssh_override_dir": override_dir,
        "mutex": SandboxMutex(),
        "override_owner": _OWNER_ID,
    }


def _verify_api_version(api):
    from ..mcp.server import verify_api_version
    verify_api_version(api, expected_major=EXPECTED_API_MAJOR)


def run_server(*, repo_root: Path, call_timeout: int,
               skip_version_check: bool) -> None:
    from mcp.server.fastmcp import FastMCP
    from .tools import inspect as inspect_tools
    from .tools import run as run_tools
    from .tools import fixtures as fixture_tools

    try:
        ctx = _build_context(repo_root)
    except SandboxConfigError as e:
        click.echo(f"FATAL: {e}", err=True)
        sys.exit(1)
    ctx["call_timeout"] = int(call_timeout)

    if not skip_version_check:
        try:
            _verify_api_version(ctx["api"])
        except Exception as e:
            click.echo(f"FATAL: API version check failed: {e}", err=True)
            sys.exit(1)

    server = FastMCP("pdm-sandbox")
    inspect_tools.register(server, ctx)
    run_tools.register(server, ctx)
    fixture_tools.register(server, ctx)
    server.run(transport="stdio")


def cleanup(repo_root: Path) -> None:
    """Remove stale replay-*.yaml from override-dir."""
    override_dir = repo_root / ".pdm" / "sandbox" / "ssh-overrides"
    removed = 0
    if override_dir.is_dir():
        for p in override_dir.glob("replay-*.yaml"):
            try:
                p.unlink()
                removed += 1
            except Exception as e:
                click.echo(f"failed to remove {p}: {e}", err=True)
    click.echo(f"cleanup-overrides: removed {removed} stale file(s)")
