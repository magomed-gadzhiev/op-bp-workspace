"""CLI entry for `pdm mcp serve --env=prod|sandbox`."""

from __future__ import annotations

import sys

import click


def _require_mcp_sdk() -> None:
    """Verify mcp SDK is importable; exit with hint if not."""
    try:
        import mcp  # noqa: F401
        import mcp.server.fastmcp  # noqa: F401
    except ImportError:
        click.echo(
            "pdm-mcp requires the 'mcp' extras. Install with:\n"
            "  pip install 'pdm-cli[mcp]'",
            err=True,
        )
        sys.exit(1)


@click.group("mcp")
def mcp_group():
    """Read-only MCP server for AI-agent consumption."""


@mcp_group.command("serve")
@click.option(
    "--env",
    required=True,
    type=click.Choice(["prod", "sandbox"]),
    help="Which PDM environment to expose.",
)
@click.option(
    "--skip-version-check",
    is_flag=True,
    default=False,
    help="Skip pdm_api_version handshake (use with caution).",
)
@click.pass_context
def serve(ctx, env, skip_version_check):
    """Start a stdio MCP server pointed at the specified PDM environment."""
    _require_mcp_sdk()
    # Server module imported lazily after SDK check
    from pathlib import Path

    from .server import run_server

    cwd = Path((ctx.obj or {}).get("cwd") or ".").resolve()
    run_server(env=env, repo_root=cwd, skip_version_check=skip_version_check)
