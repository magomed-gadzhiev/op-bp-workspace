import respx
from click.testing import CliRunner

from pdm_cli.cli import main


SB = "https://sb.local"


def _stage_repo(tmp_path):
    (tmp_path / "pdm.config.yaml").write_text(
        f"endpoints:\n  prod: http://p\n  sandbox: {SB}\n", encoding="utf-8"
    )
    (tmp_path / ".pdm").mkdir(exist_ok=True)
    (tmp_path / ".pdm" / "secrets.yaml").write_text(
        "api_key_prod: P\napi_key_sandbox: S\ncli_bypass_secret: B\n",
        encoding="utf-8",
    )


@respx.mock
def test_pull_one_bp_from_sandbox(tmp_path):
    _stage_repo(tmp_path)
    respx.get(f"{SB}/api/business-processes/payroll/full/").respond(json={
        "manifest": {"slug": "payroll", "name": "Payroll v2",
                     "description": "Updated", "version": 3, "status": "draft",
                     "owner": None},
        "entities": [], "tasks": [],
    })

    runner = CliRunner()
    result = runner.invoke(
        main, ["pull", "--from", "sandbox", "--bp", "payroll"],
        obj={"cwd": tmp_path},
    )
    assert result.exit_code == 0, result.output
    manifest = (tmp_path / "processes" / "payroll" / "manifest.yaml").read_text(
        encoding="utf-8"
    )
    assert "Payroll v2" in manifest
    assert "version: 3" in manifest


@respx.mock
def test_pull_all_when_no_bp_filter(tmp_path):
    _stage_repo(tmp_path)
    respx.get(f"{SB}/api/business-processes/").respond(
        json=[{"slug": "a"}, {"slug": "b"}]
    )
    for slug in ("a", "b"):
        respx.get(f"{SB}/api/business-processes/{slug}/full/").respond(json={
            "manifest": {"slug": slug, "name": slug.upper(), "description": "",
                         "version": 1, "status": "draft", "owner": None},
            "entities": [], "tasks": [],
        })

    runner = CliRunner()
    result = runner.invoke(main, ["pull", "--from", "sandbox"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert (tmp_path / "processes" / "a" / "manifest.yaml").exists()
    assert (tmp_path / "processes" / "b" / "manifest.yaml").exists()


@respx.mock
def test_pull_default_is_prod(tmp_path):
    _stage_repo(tmp_path)
    # Mock prod, NOT sandbox
    respx.get("http://p/api/business-processes/").respond(json=[])
    runner = CliRunner()
    result = runner.invoke(main, ["pull"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "from prod" in result.output
