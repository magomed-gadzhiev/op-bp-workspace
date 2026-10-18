import shutil
import subprocess
from pathlib import Path

import respx
from click.testing import CliRunner

from pdm_cli.cli import main


PROD = "https://prod.local"
SAMPLE = Path(__file__).parent / "fixtures" / "sample-repo"


def _git_init(cwd):
    subprocess.run(["git", "init", "-q"], cwd=cwd, check=True)
    subprocess.run(["git", "add", "."], cwd=cwd, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T",
         "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"],
        cwd=cwd, check=True,
    )


def _stage(tmp_path):
    shutil.copytree(SAMPLE, tmp_path, dirs_exist_ok=True)
    (tmp_path / "pdm.config.yaml").write_text(
        f"endpoints:\n  prod: {PROD}\n  sandbox: http://sb\n",
        encoding="utf-8",
    )
    (tmp_path / ".pdm").mkdir(exist_ok=True)
    (tmp_path / ".pdm" / "secrets.yaml").write_text(
        "api_key_prod: P\napi_key_sandbox: S\ncli_bypass_secret: B\n",
        encoding="utf-8",
    )
    _git_init(tmp_path)


def _full_resp(slug, version, status):
    return {
        "manifest": {"slug": slug, "name": slug.title(), "description": "",
                     "version": version, "status": status, "owner": None},
        "entities": [], "tasks": [],
    }


@respx.mock
def test_promote_imports_then_publishes(tmp_path):
    _stage(tmp_path)
    subprocess.run(["git", "tag", "v0.1.0"], cwd=tmp_path, check=True)

    respx.post(f"{PROD}/api/business-processes/payroll/import_full/").respond(
        status_code=201, json=_full_resp("payroll", 5, "draft")
    )
    promote_route = respx.post(
        f"{PROD}/api/business-processes/payroll/promote/"
    ).respond(json=_full_resp("payroll", 5, "published"))

    runner = CliRunner()
    result = runner.invoke(main, ["promote", "v0.1.0"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert promote_route.called

    body = promote_route.calls.last.request.read().decode()
    assert "v0.1.0" in body
    assert '"version": 5' in body or '"version":5' in body


def test_promote_refuses_unknown_tag(tmp_path):
    _stage(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["promote", "v9.9.9"], obj={"cwd": tmp_path})
    assert result.exit_code != 0
    assert "tag" in result.output.lower()


@respx.mock
def test_promote_uses_bypass_header(tmp_path):
    _stage(tmp_path)
    subprocess.run(["git", "tag", "v0.2.0"], cwd=tmp_path, check=True)

    import_route = respx.post(
        f"{PROD}/api/business-processes/payroll/import_full/"
    ).respond(status_code=201, json=_full_resp("payroll", 1, "draft"))
    respx.post(f"{PROD}/api/business-processes/payroll/promote/").respond(
        json=_full_resp("payroll", 1, "published")
    )

    runner = CliRunner()
    result = runner.invoke(main, ["promote", "v0.2.0"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output

    sent = import_route.calls.last.request
    assert sent.headers.get("X-Pdm-Cli-Bypass") == "B"


def test_promote_empty_repo(tmp_path):
    """Repo without processes/ — promote gracefully reports nothing."""
    (tmp_path / "pdm.config.yaml").write_text(
        f"endpoints:\n  prod: {PROD}\n  sandbox: http://sb\n", encoding="utf-8"
    )
    (tmp_path / ".pdm").mkdir()
    (tmp_path / ".pdm" / "secrets.yaml").write_text(
        "api_key_prod: P\napi_key_sandbox: S\ncli_bypass_secret: B\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    # Need at least one commit to create a tag
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T",
         "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"],
        cwd=tmp_path, check=True,
    )
    subprocess.run(["git", "tag", "v0.0.1"], cwd=tmp_path, check=True)

    runner = CliRunner()
    result = runner.invoke(main, ["promote", "v0.0.1"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "No processes" in result.output
