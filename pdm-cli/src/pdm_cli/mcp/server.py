"""FastMCP server assembly for `pdm mcp serve`."""

from __future__ import annotations

import sys
from pathlib import Path

import click


EXPECTED_API_MAJOR = "1"


class ApiVersionMismatch(RuntimeError):
    pass


def verify_api_version(api, expected_major: str = EXPECTED_API_MAJOR) -> None:
    h = api.health() or {}
    got = h.get("pdm_api_version")
    if not got:
        raise ApiVersionMismatch(
            "PDM /api/health/ does not expose pdm_api_version — "
            "upgrade PDM backend or pass --skip-version-check"
        )
    got_major = str(got).split(".")[0]
    if got_major != expected_major:
        raise ApiVersionMismatch(
            f"PDM API version mismatch: server={got}, "
            f"client supports={expected_major}.x"
        )


def make_server(*, env: str, repo_root: Path, api, journals, feedback_reader):
    from mcp.server.fastmcp import FastMCP
    from .tools import processes, schemas, telemetry, feedback

    server = FastMCP(f"pdm-{env}")
    processes.register(server, api)
    schemas.register(server, api)
    telemetry.register(server, api, journals=journals)
    feedback.register(server, feedback_reader)
    return server


def _build_api(env: str, repo_root: Path):
    from ..api_client import PdmApiClient
    from ..config import ConfigError, load_config
    cfg = load_config(repo_root)
    base_url = cfg.endpoint(env)
    try:
        token = cfg.read_api_key(env)
    except ConfigError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    return PdmApiClient(base_url=base_url, api_key=token)


def run_server(*, env: str, repo_root: Path, skip_version_check: bool = False) -> None:
    from .readers.feedback_fs import FeedbackReader
    from .readers.run_journal import RunJournalReader

    api = _build_api(env, repo_root)
    if not skip_version_check:
        try:
            verify_api_version(api)
        except ApiVersionMismatch as e:
            click.echo(f"FATAL: {e}", err=True)
            sys.exit(1)
        except Exception as e:
            click.echo(
                f"FATAL: PDM API unreachable during version check: {e}",
                err=True,
            )
            sys.exit(1)
    journals = RunJournalReader(repo_root / ".pdm" / "runs") if env == "sandbox" else None
    feedback_reader = FeedbackReader(repo_root / "feedback" / "tickets")
    server = make_server(
        env=env, repo_root=repo_root,
        api=api, journals=journals, feedback_reader=feedback_reader,
    )
    server.run(transport="stdio")
