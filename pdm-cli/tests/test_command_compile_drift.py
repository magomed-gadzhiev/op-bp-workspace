"""Командные тесты: pdm compile (Tier 0) и pdm drift (информационное сравнение)."""

import respx
from click.testing import CliRunner

from .test_bpm_package import make_package
from pdm_cli.bpm_package import build_zip, write_package
from pdm_cli.cli import main

API = "http://pdm.local"


def _seed_repo(tmp_path, monkeypatch):
    write_package(tmp_path, make_package())
    monkeypatch.setenv("PDM_API_BASE", API)
    monkeypatch.setenv("PDM_API_TOKEN", "test-token")


def test_compile_ok(tmp_path):
    write_package(tmp_path, make_package())
    runner = CliRunner()
    result = runner.invoke(main, ["compile"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "testbp" in result.output
    assert "Tier 0" in result.output


def test_compile_invalid_package_fails(tmp_path):
    write_package(tmp_path, make_package())
    # ломаем перекрёстную ссылку: биндинг на несуществующий скрипт
    task_file = tmp_path / "processes" / "testbp" / "tasks" / "01-formirovanie.yaml"
    task_file.write_text(
        "name: Формирование\nscript_bindings:\n- script_name: ghost\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(main, ["compile"], obj={"cwd": tmp_path})
    assert result.exit_code == 1
    assert "ghost" in result.output


def test_compile_unknown_bp_fails(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["compile", "--bp", "nope"], obj={"cwd": tmp_path})
    assert result.exit_code == 2


@respx.mock
def test_drift_clean_exits_zero(tmp_path, monkeypatch):
    _seed_repo(tmp_path, monkeypatch)
    pkg = make_package()
    data, _ = build_zip(pkg)
    respx.post(f"{API}/api/business-processes/1/export/").respond(content=data)
    respx.get(f"{API}/api/business-processes/").respond(json=[
        {"id": 1, "slug": "testbp", "name": "Тестовый БП"},
    ])
    runner = CliRunner()
    result = runner.invoke(main, ["drift"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "дрейфа нет" in result.output


@respx.mock
def test_drift_detects_server_side_change(tmp_path, monkeypatch):
    _seed_repo(tmp_path, monkeypatch)
    remote = make_package()
    remote.business_process.tasks[0].description = "изменено в UI"
    data, _ = build_zip(remote)
    respx.post(f"{API}/api/business-processes/1/export/").respond(content=data)
    respx.get(f"{API}/api/business-processes/").respond(json=[
        {"id": 1, "slug": "testbp", "name": "Тестовый БП"},
    ])
    runner = CliRunner()
    result = runner.invoke(main, ["drift"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "description" in result.output
    assert "на сервере" in result.output


@respx.mock
def test_drift_json_output(tmp_path, monkeypatch):
    _seed_repo(tmp_path, monkeypatch)
    remote = make_package()
    remote.document_templates[0].description = "server-side"
    data, _ = build_zip(remote)
    respx.post(f"{API}/api/business-processes/1/export/").respond(content=data)
    respx.get(f"{API}/api/business-processes/").respond(json=[
        {"id": 1, "slug": "testbp", "name": "Тестовый БП"},
    ])
    runner = CliRunner()
    result = runner.invoke(main, ["drift", "--json"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert '"testbp"' in result.output


def test_drift_invalid_local_package_fails(tmp_path, monkeypatch):
    _seed_repo(tmp_path, monkeypatch)
    task_file = tmp_path / "processes" / "testbp" / "tasks" / "01-formirovanie.yaml"
    task_file.write_text(
        "name: Формирование\nscript_bindings:\n- script_name: ghost\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(main, ["drift"], obj={"cwd": tmp_path})
    assert result.exit_code == 1
    assert "ghost" in result.output


def test_drift_unknown_bp_fails(tmp_path, monkeypatch):
    _seed_repo(tmp_path, monkeypatch)
    runner = CliRunner()
    result = runner.invoke(main, ["drift", "--bp", "nope"], obj={"cwd": tmp_path})
    assert result.exit_code == 2
