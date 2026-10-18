import shutil
from pathlib import Path

import respx
from click.testing import CliRunner

from pdm_cli.cli import main


SB = "https://sb.local"
SAMPLE = Path(__file__).parent / "fixtures" / "sample-repo"


def _prep(tmp_path):
    shutil.copytree(SAMPLE, tmp_path, dirs_exist_ok=True)
    (tmp_path / "pdm.config.yaml").write_text(
        f"endpoints:\n  prod: http://p\n  sandbox: {SB}\n", encoding="utf-8"
    )
    (tmp_path / ".pdm").mkdir(exist_ok=True)
    (tmp_path / ".pdm" / "secrets.yaml").write_text(
        "api_key_prod: P\napi_key_sandbox: S\ncli_bypass_secret: B\n",
        encoding="utf-8",
    )


@respx.mock
def test_diff_no_differences(tmp_path):
    _prep(tmp_path)
    # Remote is identical to fixture
    respx.get(f"{SB}/api/business-processes/payroll/full/").respond(json={
        "manifest": {"slug": "payroll", "name": "Payroll",
                     "description": "Расчёт зарплаты", "version": 1,
                     "status": "draft", "owner": None},
        "entities": [{"slug": "employee", "name": "Employee",
                      "fields": [{"name": "id", "type": "int"},
                                 {"name": "full_name", "type": "str"}],
                      "validation": {}}],
        "tasks": [{"slug": "calc-bonus", "title": "Calculate bonus",
                   "kind": "script", "config": {}}],
    })

    runner = CliRunner()
    result = runner.invoke(main, ["diff", "--against", "sandbox"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "No differences" in result.output


@respx.mock
def test_diff_shows_local_changes(tmp_path):
    _prep(tmp_path)
    # Remote has different name
    respx.get(f"{SB}/api/business-processes/payroll/full/").respond(json={
        "manifest": {"slug": "payroll", "name": "DIFFERENT NAME",
                     "description": "Расчёт зарплаты", "version": 1,
                     "status": "draft", "owner": None},
        "entities": [], "tasks": [],
    })

    runner = CliRunner()
    result = runner.invoke(main, ["diff", "--against", "sandbox"], obj={"cwd": tmp_path})
    assert result.exit_code == 0
    # Should show diff including remote name
    assert "DIFFERENT NAME" in result.output or "Payroll" in result.output


@respx.mock
def test_diff_remote_404_reported(tmp_path):
    """If a local BP doesn't exist remotely (404), it's reported as a diff."""
    _prep(tmp_path)
    respx.get(f"{SB}/api/business-processes/payroll/full/").respond(status_code=404)

    runner = CliRunner()
    result = runner.invoke(main, ["diff", "--against", "sandbox"], obj={"cwd": tmp_path})
    assert result.exit_code == 0
    assert "not present" in result.output.lower() or "404" in result.output


def test_state_normalize_changes_on_script_code_edit():
    """State canonicalization must change when a script's code changes,
    so `pdm push`/`pdm diff` detect a script body edit."""
    from pdm_cli.commands.diff import _normalize
    from pdm_cli.models import Manifest, Process, Script

    p1 = Process(
        manifest=Manifest(slug="bp1", name="BP1", version=1, status="draft"),
        scripts=[Script(name="s1", code="v1")],
    )
    p2 = Process(
        manifest=Manifest(slug="bp1", name="BP1", version=1, status="draft"),
        scripts=[Script(name="s1", code="v2")],
    )
    assert _normalize(p1) != _normalize(p2)


def test_state_normalize_changes_on_script_meta_edit():
    """State canonicalization must change when script metadata changes,
    so editing <script>.meta.yaml triggers a push."""
    from pdm_cli.commands.diff import _normalize
    from pdm_cli.models import Manifest, Process, Script

    p1 = Process(
        manifest=Manifest(slug="bp1", name="BP1", version=1, status="draft"),
        scripts=[Script(name="s1", code="x", description="a")],
    )
    p2 = Process(
        manifest=Manifest(slug="bp1", name="BP1", version=1, status="draft"),
        scripts=[Script(name="s1", code="x", description="b")],
    )
    assert _normalize(p1) != _normalize(p2)


def test_state_normalize_stable_when_scripts_unchanged():
    """Identical scripts produce identical state — no spurious diffs."""
    from pdm_cli.commands.diff import _normalize
    from pdm_cli.models import Manifest, Process, Script

    p1 = Process(
        manifest=Manifest(slug="bp1", name="BP1", version=1, status="draft"),
        scripts=[Script(name="s1", code="x", description="a")],
    )
    p2 = Process(
        manifest=Manifest(slug="bp1", name="BP1", version=1, status="draft"),
        scripts=[Script(name="s1", code="x", description="a")],
    )
    assert _normalize(p1) == _normalize(p2)


def test_diff_empty_repo(tmp_path):
    """No local processes — graceful exit."""
    (tmp_path / "pdm.config.yaml").write_text(
        f"endpoints:\n  prod: http://p\n  sandbox: {SB}\n", encoding="utf-8"
    )
    (tmp_path / ".pdm").mkdir()
    (tmp_path / ".pdm" / "secrets.yaml").write_text(
        "api_key_prod: P\napi_key_sandbox: S\ncli_bypass_secret: B\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(main, ["diff", "--against", "sandbox"], obj={"cwd": tmp_path})
    assert result.exit_code == 0
    assert "No processes" in result.output
