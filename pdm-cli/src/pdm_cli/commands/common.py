"""Общие опции подключения для пакетных команд (compile/push/pull/drift).

В монорепо нет pdm.config.yaml (он — артефакт client-project), поэтому
приоритет: явные опции → переменные окружения PDM_API_BASE/PDM_API_TOKEN →
pdm.config.yaml окружение sandbox/prod.
"""

from __future__ import annotations

import os
from pathlib import Path

import click
from rich.console import Console

from ..api_client import PdmApiClient
from ..config import Config, load_config

console = Console()


def api_options(f):
    """Декоратор, добавляющий --api-base/--api-key/--env."""
    f = click.option("--api-key", "api_key", default=None,
                     help="PDM API token (default: PDM_API_TOKEN env).")(f)
    f = click.option("--api-base", "api_base", default=None,
                     help="PDM API base URL (default: PDM_API_BASE env).")(f)
    return f


def make_client(ctx, api_base: str | None, api_key: str | None) -> PdmApiClient:
    base = api_base or os.environ.get("PDM_API_BASE")
    key = api_key or os.environ.get("PDM_API_TOKEN")
    if base and key:
        return PdmApiClient(base_url=base, api_key=key, timeout=120.0)
    # Fallback: pdm.config.yaml (client-project репо)
    cwd = Path((ctx.obj or {}).get("cwd") or ".")
    cfg: Config = load_config(cwd)
    env = "sandbox"
    return PdmApiClient(
        base_url=cfg.endpoint(env),
        api_key=cfg.api_key(env),
        cli_bypass_secret=cfg.cli_bypass_secret,
        timeout=120.0,
    )
