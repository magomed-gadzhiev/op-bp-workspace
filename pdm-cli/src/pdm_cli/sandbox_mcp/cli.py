"""CLI entry for `pdm sandbox-mcp serve` (Etap 7).

Hard-coded sandbox-only — there is no --env flag. The server cannot point at
prod by construction.
"""
from __future__ import annotations

import sys

import click


def _require_mcp_sdk() -> None:
    try:
        import mcp  # noqa: F401
        import mcp.server.fastmcp  # noqa: F401
    except ImportError:
        click.echo(
            "pdm-sandbox-mcp requires the 'mcp' extras. Install with:\n"
            "  pip install 'pdm-cli[mcp]'",
            err=True,
        )
        sys.exit(1)


@click.group("sandbox-mcp")
def sandbox_mcp_group():
    """Interactive sandbox MCP server (mutating tool-calls)."""


@sandbox_mcp_group.command("serve")
@click.option("--call-timeout", default=300, type=int,
              help="Per-tool-call timeout in seconds (default 300, max 600).")
@click.option("--skip-version-check", is_flag=True, default=False,
              help="Skip pdm_api_version handshake.")
@click.pass_context
def serve(ctx, call_timeout, skip_version_check):
    """Start a stdio MCP server bound to the sandbox environment."""
    _require_mcp_sdk()
    from pathlib import Path
    from .server import run_server

    if call_timeout > 600:
        click.echo("--call-timeout capped at 600s", err=True)
        call_timeout = 600

    cwd = Path((ctx.obj or {}).get("cwd") or ".").resolve()
    run_server(repo_root=cwd, call_timeout=call_timeout,
               skip_version_check=skip_version_check)


@sandbox_mcp_group.command("cleanup-overrides")
@click.pass_context
def cleanup_overrides(ctx):
    """Remove stale replay-*.yaml from override-dir."""
    from pathlib import Path
    from .server import cleanup as _cleanup
    cwd = Path((ctx.obj or {}).get("cwd") or ".").resolve()
    _cleanup(cwd)
