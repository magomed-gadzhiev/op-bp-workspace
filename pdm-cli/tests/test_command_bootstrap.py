from unittest.mock import MagicMock, patch

import respx
from click.testing import CliRunner

from pdm_cli.cli import main


PROD = "https://prod.local"
SB = "https://sandbox.local"


@respx.mock
def test_bootstrap_creates_config_and_pulls_processes(tmp_path):
    respx.get(f"{PROD}/api/business-processes/").respond(
        json=[{"slug": "payroll", "name": "Payroll"}]
    )
    respx.get(f"{PROD}/api/business-processes/payroll/full/").respond(json={
        "manifest": {"slug": "payroll", "name": "Payroll", "description": "",
                     "version": 1, "status": "published", "owner": None},
        "entities": [], "tasks": [],
    })

    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "K",
        "--sandbox-url", SB, "--api-key-sandbox", "S",
    ], obj={"cwd": tmp_path})

    assert result.exit_code == 0, result.output
    assert (tmp_path / "pdm.config.yaml").is_file()
    assert (tmp_path / ".pdm" / "secrets.yaml").is_file()
    assert (tmp_path / ".gitignore").is_file()
    assert (tmp_path / "processes" / "payroll" / "manifest.yaml").is_file()


@respx.mock
def test_bootstrap_writes_endpoints_and_secrets(tmp_path):
    respx.get(f"{PROD}/api/business-processes/").respond(json=[])

    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "PK",
        "--sandbox-url", SB, "--api-key-sandbox", "SK",
    ], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output

    cfg = (tmp_path / "pdm.config.yaml").read_text(encoding="utf-8")
    assert PROD in cfg
    assert SB in cfg

    secrets = (tmp_path / ".pdm" / "secrets.yaml").read_text(encoding="utf-8")
    assert "PK" in secrets
    assert "SK" in secrets


@respx.mock
def test_bootstrap_gitignore_contains_secrets_path(tmp_path):
    respx.get(f"{PROD}/api/business-processes/").respond(json=[])
    runner = CliRunner()
    runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "K",
        "--sandbox-url", SB, "--api-key-sandbox", "S",
    ], obj={"cwd": tmp_path})
    gi = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".pdm/secrets.yaml" in gi


@respx.mock
def test_bootstrap_extends_existing_gitignore(tmp_path):
    """If .gitignore already exists, bootstrap appends rather than overwrites."""
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    respx.get(f"{PROD}/api/business-processes/").respond(json=[])
    runner = CliRunner()
    runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "K",
        "--sandbox-url", SB, "--api-key-sandbox", "S",
    ], obj={"cwd": tmp_path})
    gi = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "node_modules/" in gi  # preserved
    assert ".pdm/secrets.yaml" in gi  # appended


def test_bootstrap_refuses_if_repo_already_initialized(tmp_path):
    (tmp_path / "pdm.config.yaml").write_text("x", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "K",
        "--sandbox-url", SB, "--api-key-sandbox", "S",
    ], obj={"cwd": tmp_path})

    assert result.exit_code != 0
    out = result.output.lower()
    assert "already" in out or "exists" in out


def test_bootstrap_refuses_if_processes_dir_exists(tmp_path):
    (tmp_path / "processes").mkdir()

    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "K",
        "--sandbox-url", SB, "--api-key-sandbox", "S",
    ], obj={"cwd": tmp_path})

    assert result.exit_code != 0


@respx.mock
def test_bootstrap_skips_legacy_bps_without_slug(tmp_path):
    """Legacy BPs that haven't been backfilled with slug are skipped with warning."""
    respx.get(f"{PROD}/api/business-processes/").respond(json=[
        {"id": 17, "name": "Legacy BP without slug"},
        {"slug": "good-one", "name": "Has slug"},
    ])
    respx.get(f"{PROD}/api/business-processes/good-one/full/").respond(json={
        "manifest": {"slug": "good-one", "name": "Has slug", "description": "",
                     "version": 1, "status": "published", "owner": None},
        "entities": [], "tasks": [],
    })

    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "K",
        "--sandbox-url", SB, "--api-key-sandbox", "S",
    ], obj={"cwd": tmp_path})

    assert result.exit_code == 0, result.output
    assert (tmp_path / "processes" / "good-one" / "manifest.yaml").is_file()
    assert "Skipped" in result.output


@respx.mock
def test_bootstrap_empty_pdm_no_processes(tmp_path):
    respx.get(f"{PROD}/api/business-processes/").respond(json=[])

    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "K",
        "--sandbox-url", SB, "--api-key-sandbox", "S",
    ], obj={"cwd": tmp_path})

    assert result.exit_code == 0
    assert (tmp_path / "pdm.config.yaml").is_file()  # config still written
    # No processes/<slug>/ dirs created
    proc_dir = tmp_path / "processes"
    assert (not proc_dir.exists()) or (not any(proc_dir.iterdir()))


@respx.mock
def test_bootstrap_writes_readme_from_template(tmp_path):
    respx.get(f"{PROD}/api/business-processes/").respond(json=[])
    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "K",
        "--sandbox-url", SB, "--api-key-sandbox", "S",
    ], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    readme = (tmp_path / "README.md")
    assert readme.is_file()
    content = readme.read_text(encoding="utf-8")
    assert "PDM Client Project" in content
    assert "pdm validate" in content


@respx.mock
def test_bootstrap_does_not_overwrite_existing_readme(tmp_path):
    (tmp_path / "README.md").write_text(
        "# Custom README I already wrote", encoding="utf-8"
    )
    respx.get(f"{PROD}/api/business-processes/").respond(json=[])
    runner = CliRunner()
    runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "K",
        "--sandbox-url", SB, "--api-key-sandbox", "S",
    ], obj={"cwd": tmp_path})
    content = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "Custom README I already wrote" in content
    assert "PDM Client Project" not in content


# ---------------------------------------------------------------------------
# workflows (n8n removed): bootstrap must not scaffold workflow dirs
# ---------------------------------------------------------------------------


@respx.mock
def test_bootstrap_does_not_create_workflows_dir(tmp_path):
    """n8n integration removed — no processes/<slug>/workflows/ is created."""
    respx.get(f"{PROD}/api/business-processes/").respond(
        json=[{"slug": "payroll", "name": "Payroll"}]
    )
    respx.get(f"{PROD}/api/business-processes/payroll/full/").respond(json={
        "manifest": {"slug": "payroll", "name": "Payroll", "description": "",
                     "version": 1, "status": "published", "owner": None},
        "entities": [], "tasks": [],
    })

    runner = CliRunner()
    result = runner.invoke(main, [
        "bootstrap",
        "--pdm-url", PROD, "--api-key", "K",
        "--sandbox-url", SB, "--api-key-sandbox", "S",
    ], obj={"cwd": tmp_path})

    assert result.exit_code == 0, result.output
    assert (tmp_path / "processes" / "payroll" / "manifest.yaml").is_file()
    assert not (tmp_path / "processes" / "payroll" / "workflows").exists()
