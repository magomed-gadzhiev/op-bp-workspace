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


def test_push_refuses_to_prod(tmp_path):
    _prep(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["push", "--to", "prod"], obj={"cwd": tmp_path})
    assert result.exit_code != 0
    assert "promote" in result.output.lower()


@respx.mock
def test_push_imports_all_bps_to_sandbox(tmp_path):
    _prep(tmp_path)
    route = respx.post(f"{SB}/api/business-processes/payroll/import_full/").respond(
        status_code=201, json={
            "manifest": {"slug": "payroll", "name": "Payroll", "description": "Расчёт зарплаты",
                         "version": 2, "status": "draft", "owner": None},
            "entities": [], "tasks": [],
        }
    )

    runner = CliRunner()
    result = runner.invoke(main, ["push", "--to", "sandbox"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert route.called

    sent = route.calls.last.request
    assert sent.headers.get("X-Pdm-Cli-Bypass") == "B"


@respx.mock
def test_push_one_bp_filter(tmp_path):
    _prep(tmp_path)
    route = respx.post(f"{SB}/api/business-processes/payroll/import_full/").respond(
        status_code=201, json={
            "manifest": {"slug": "payroll", "name": "Payroll", "description": "",
                         "version": 2, "status": "draft", "owner": None},
            "entities": [], "tasks": [],
        }
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["push", "--to", "sandbox", "--bp", "payroll"],
        obj={"cwd": tmp_path},
    )
    assert result.exit_code == 0, result.output
    assert route.called


def test_push_empty_repo(tmp_path):
    """Repo without processes/ — push gracefully reports nothing to do."""
    (tmp_path / "pdm.config.yaml").write_text(
        f"endpoints:\n  prod: http://p\n  sandbox: {SB}\n", encoding="utf-8"
    )
    (tmp_path / ".pdm").mkdir()
    (tmp_path / ".pdm" / "secrets.yaml").write_text(
        "api_key_prod: P\napi_key_sandbox: S\ncli_bypass_secret: B\n",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(main, ["push", "--to", "sandbox"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "No processes" in result.output


@respx.mock
def test_pull_edit_push_round_trip_preserves_script_code(tmp_path):
    """E2E: pdm pull → edit .py → pdm push sends new code to the backend."""
    import json

    (tmp_path / "pdm.config.yaml").write_text(
        f"endpoints:\n  prod: http://p\n  sandbox: {SB}\n", encoding="utf-8"
    )
    (tmp_path / ".pdm").mkdir(exist_ok=True)
    (tmp_path / ".pdm" / "secrets.yaml").write_text(
        "api_key_prod: P\napi_key_sandbox: S\ncli_bypass_secret: B\n",
        encoding="utf-8",
    )

    full_response = {
        "manifest": {
            "slug": "bp1", "name": "BP1", "description": "",
            "version": 1, "status": "draft", "owner": None,
        },
        "entities": [],
        "tasks": [],
        "scripts": [{
            "name": "s1",
            "display_name": "S1",
            "description": "",
            "status": "active",
            "code": "old",
            "requirements": "",
        }],
    }
    respx.get(f"{SB}/api/business-processes/bp1/full/").respond(json=full_response)

    runner = CliRunner()
    r = runner.invoke(
        main, ["pull", "--from", "sandbox", "--bp", "bp1"], obj={"cwd": tmp_path}
    )
    assert r.exit_code == 0, r.output

    py_path = tmp_path / "processes" / "bp1" / "scripts" / "s1.py"
    assert py_path.read_text(encoding="utf-8") == "old"

    py_path.write_text("new", encoding="utf-8")

    import_route = respx.post(
        f"{SB}/api/business-processes/bp1/import_full/"
    ).respond(status_code=201, json={
        **full_response,
        "manifest": {**full_response["manifest"], "version": 2},
        "scripts": [{**full_response["scripts"][0], "code": "new"}],
    })

    r = runner.invoke(
        main, ["push", "--to", "sandbox", "--bp", "bp1"], obj={"cwd": tmp_path}
    )
    assert r.exit_code == 0, r.output
    assert import_route.called

    captured = json.loads(import_route.calls.last.request.read())
    assert len(captured["scripts"]) == 1
    assert captured["scripts"][0]["name"] == "s1"
    assert captured["scripts"][0]["code"] == "new"
