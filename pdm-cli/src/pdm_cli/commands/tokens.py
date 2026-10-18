"""pdm tokens — read-token management."""

import io
import os
import sys
from pathlib import Path

import click
import httpx
from ruamel.yaml import YAML

from ..config import load_config


@click.group("tokens")
def tokens_group():
    """Manage PDM API tokens used by pdm-cli and pdm-mcp."""


@tokens_group.command("rotate-read")
@click.option("--env", required=True, type=click.Choice(["prod", "sandbox"]))
@click.pass_context
def rotate_read(ctx, env):
    """Mint a fresh read-only token for the given env via PDM internal API."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".").resolve()
    cfg = load_config(cwd)
    base = cfg.endpoint(env)
    internal_token = os.environ.get("PDM_INTERNAL_API_TOKEN")
    if not internal_token:
        click.echo(
            "PDM_INTERNAL_API_TOKEN env var required (issued at PDM deploy time).",
            err=True,
        )
        sys.exit(2)

    username = f"pdm-mcp-read-{env}"
    r = httpx.post(
        f"{base.rstrip('/')}/api/internal/tokens/create-readonly/",
        json={"username": username},
        headers={"X-PDM-Internal-Token": internal_token},
        timeout=15.0,
    )
    r.raise_for_status()
    token = r.json()["token"]

    secrets_path = cwd / ".pdm" / "secrets.yaml"
    y = YAML()
    y.preserve_quotes = True
    data = y.load(secrets_path.read_text(encoding="utf-8")) or {}
    data[f"read_api_key_{env}"] = token
    buf = io.StringIO()
    y.dump(data, buf)
    secrets_path.write_text(buf.getvalue(), encoding="utf-8")
    click.echo(f"Wrote read_api_key_{env} to {secrets_path}")
