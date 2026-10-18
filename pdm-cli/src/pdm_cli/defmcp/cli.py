"""CLI entry for `pdm defmcp serve` (спека 143, ADR-0059).

HTTP-транспорт — для контейнера mcp-pdm-bp (LibreChat), stdio — для
локальных агентских клиентов. Корень репо содержит конфиг песочницы и
.pdm/ (workspace черновиков создаётся при первом инструменте).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click


def _require_mcp_sdk() -> None:
    try:
        import mcp  # noqa: F401
        import mcp.server.fastmcp  # noqa: F401
    except ImportError:
        click.echo(
            "pdm defmcp requires the 'mcp' extras. Install with:\n"
            "  pip install 'pdm-cli[mcp]'",
            err=True,
        )
        sys.exit(1)


@click.group("defmcp")
def defmcp_group():
    """Chat-edit MCP server для тестовой версии БП (спека 143)."""


@defmcp_group.command("serve")
@click.option("--transport", type=click.Choice(["http", "stdio"]),
              default="http", show_default=True)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8016, type=int, show_default=True)
@click.option("--repo-root", "repo_root_opt", default=None,
              type=click.Path(file_okay=False, path_type=Path),
              help="Корень репо (default: $MCP_BP_REPO_ROOT или cwd).")
@click.option("--drafts-root", "drafts_root_opt", default=None,
              type=click.Path(file_okay=False, path_type=Path),
              help="Корень workspace черновиков "
                   "(default: $MCP_BP_DRAFTS_ROOT или <repo>/.pdm/drafts).")
@click.option("--skip-version-check", is_flag=True, default=False,
              help="Пропустить pdm_api_version handshake.")
def serve(transport, host, port, repo_root_opt, drafts_root_opt,
          skip_version_check):
    """Запустить MCP-сервер правки тестовой версии БП."""
    _require_mcp_sdk()
    from .server import run_server

    root = (
        repo_root_opt
        or Path(os.environ.get("MCP_BP_REPO_ROOT") or Path.cwd())
    ).resolve()
    if not root.is_dir():
        raise click.ClickException(
            f"каталог {root} не существует — укажи --repo-root или "
            "MCP_BP_REPO_ROOT"
        )
    if drafts_root_opt is not None:
        os.environ["MCP_BP_DRAFTS_ROOT"] = str(drafts_root_opt.resolve())
    try:
        run_server(
            repo_root=root,
            transport=transport,
            host=host,
            port=port,
            skip_version_check=skip_version_check,
        )
    except SystemExit as e:
        click.echo(str(e), err=True)
        sys.exit(1)
