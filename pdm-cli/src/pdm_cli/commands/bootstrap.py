"""pdm bootstrap — initialize a fresh client-project repo."""

import importlib.resources
import os
import sys
from pathlib import Path

import click
from rich.console import Console

from ..api_client import PdmApiClient
from ..repo import write_process
from ..skills import install_skills

console = Console()


GITIGNORE_CONTENTS = """\
# pdm-cli
.pdm/secrets.yaml
.pdm/state.json
.pdm/compiled/
.pdm/last-run.json
"""

CONFIG_TEMPLATE = """\
# pdm-cli configuration
endpoints:
  prod: {prod_url}
  sandbox: {sandbox_url}

# PII redaction rules for egress proxies (used in later etaps).
# egress:
#   http:
#     redact:
#       - regex: 'Bearer [A-Za-z0-9_-]+'
#         replacement: 'Bearer <token>'
"""

SECRETS_TEMPLATE = """\
# Secrets — gitignored. Do not commit.
api_key_prod: {prod_key}
api_key_sandbox: {sandbox_key}
cli_bypass_secret: ""
"""


@click.command("bootstrap")
@click.option("--pdm-url", required=True, help="URL of the production PDM instance.")
@click.option("--api-key", required=True, help="API key for production PDM.")
@click.option("--sandbox-url", required=True, help="URL of the sandbox PDM instance.")
@click.option("--api-key-sandbox", required=True, help="API key for sandbox PDM.")
@click.pass_context
def bootstrap(
    ctx, pdm_url, api_key, sandbox_url, api_key_sandbox,
):
    """Initialize a fresh client-project repo by pulling all BPs from PDM."""
    cwd = Path((ctx.obj or {}).get("cwd") or ".")

    if (cwd / "pdm.config.yaml").exists() or (cwd / "processes").exists():
        console.print(
            f"[red]Repo at {cwd} already initialized "
            f"(pdm.config.yaml or processes/ exists).[/red]"
        )
        console.print("Use `pdm pull` to refresh, not bootstrap.")
        sys.exit(1)

    # Write config (committed)
    cfg_text = CONFIG_TEMPLATE.format(prod_url=pdm_url, sandbox_url=sandbox_url)
    (cwd / "pdm.config.yaml").write_text(cfg_text, encoding="utf-8")

    # Write secrets (gitignored)
    pdm_dir = cwd / ".pdm"
    pdm_dir.mkdir(exist_ok=True)
    (pdm_dir / "secrets.yaml").write_text(
        SECRETS_TEMPLATE.format(prod_key=api_key, sandbox_key=api_key_sandbox),
        encoding="utf-8",
    )

    # Etap 6 — mint read-only tokens for both envs (best-effort)
    import httpx as _httpx
    _internal_token = os.environ.get("PDM_INTERNAL_API_TOKEN")
    if _internal_token:
        for env_name, env_url in (("prod", pdm_url), ("sandbox", sandbox_url)):
            try:
                r = _httpx.post(
                    f"{env_url.rstrip('/')}/api/internal/tokens/create-readonly/",
                    json={"username": f"pdm-mcp-read-{env_name}"},
                    headers={"X-PDM-Internal-Token": _internal_token},
                    timeout=15.0,
                )
                r.raise_for_status()
                read_token = r.json()["token"]
                from ruamel.yaml import YAML as _YAML
                import io as _io

                sp = pdm_dir / "secrets.yaml"
                y = _YAML()
                y.preserve_quotes = True
                data = y.load(sp.read_text(encoding="utf-8")) or {}
                data[f"read_api_key_{env_name}"] = read_token
                buf = _io.StringIO()
                y.dump(data, buf)
                sp.write_text(buf.getvalue(), encoding="utf-8")
                console.print(f"  [green]minted read-only token for {env_name}[/green]")
            except Exception as e:
                console.print(
                    f"  [yellow]could not mint read token for {env_name}: {e}; "
                    f"run `pdm tokens rotate-read --env={env_name}` later[/yellow]"
                )
    else:
        console.print(
            "[yellow]PDM_INTERNAL_API_TOKEN not set — skipped read-token minting. "
            "Run `pdm tokens rotate-read --env=prod` and `--env=sandbox` after deploy.[/yellow]"
        )

    # Write .claude/mcp.json from template (only if absent)
    import importlib.resources as _res
    claude_dir = cwd / ".claude"
    claude_dir.mkdir(exist_ok=True)
    mcp_json_path = claude_dir / "mcp.json"
    if not mcp_json_path.exists():
        template_text = (
            _res.files("pdm_cli.templates").joinpath("mcp_config.json")
            .read_text(encoding="utf-8")
        )
        mcp_json_path.write_text(template_text, encoding="utf-8")

    # Extend or create .gitignore
    gi_path = cwd / ".gitignore"
    existing = gi_path.read_text(encoding="utf-8") if gi_path.exists() else ""
    if ".pdm/secrets.yaml" not in existing:
        gi_path.write_text(existing + GITIGNORE_CONTENTS, encoding="utf-8")

    # Write README from template (if not already present)
    readme_path = cwd / "README.md"
    if not readme_path.exists():
        template = (
            importlib.resources.files("pdm_cli.templates")
            .joinpath("CLIENT_PROJECT_README.md")
            .read_text(encoding="utf-8")
        )
        readme_path.write_text(template, encoding="utf-8")

    # Copy packaged Claude skills into .claude/skills/pdm/
    install_skills(cwd, force=False)

    # Pull all processes from prod
    console.print(f"[cyan]Connecting to {pdm_url}…[/cyan]")
    pulled = 0
    skipped: list[tuple[str, str]] = []
    with PdmApiClient(base_url=pdm_url, api_key=api_key) as client:
        processes_meta = client.list_processes()
        if not processes_meta:
            console.print("[yellow]No processes found in prod PDM.[/yellow]")
        for meta in processes_meta:
            slug = meta.get("slug")
            if not slug:
                # legacy BP without slug — skip with warning
                skipped.append((str(meta.get("id", "?")), "no slug — backfill on PDM side first"))
                continue
            try:
                proc = client.get_full(slug)
            except Exception as e:
                skipped.append((slug, str(e)))
                continue
            console.print(f"  pulling {slug}…")
            write_process(cwd, proc)
            pulled += 1

    if skipped:
        console.print()
        console.print("[yellow]Skipped:[/yellow]")
        for slug, reason in skipped:
            console.print(f"  - {slug}: {reason}")

    console.print(
        f"\n[green]Bootstrap complete:[/green] "
        f"{pulled} process(es) pulled into {cwd}/processes/"
    )
    console.print(
        "\n[yellow]Next steps:[/yellow]\n"
        "  1. Review the generated files (git status / git diff)\n"
        "  2. git init && git add . && git commit -m 'initial bootstrap'\n"
        "  3. Set PDM_READ_ONLY_BP=true on your prod PDM to enforce "
        "git-as-source-of-truth"
    )
