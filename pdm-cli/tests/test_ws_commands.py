"""Командные тесты: pdm ws init/check/test/report (спека 163 §4, ADR-0070).

HTTP мокается respx (как у соседних командных тестов); env
PDM_API_BASE/PDM_API_TOKEN — через monkeypatch (приоритет common.make_client).
"""

import json

import httpx
import respx
from click.testing import CliRunner

from pdm_cli.bpm_package import build_zip, write_package
from pdm_cli.cli import main
from pdm_cli.commands import ws as ws_module
from .test_bpm_package import make_package

API = "http://pdm.local"


def _seed_env(monkeypatch):
    monkeypatch.setenv("PDM_API_BASE", API)
    monkeypatch.setenv("PDM_API_TOKEN", "test-token")


def _seed_workspace(tmp_path, monkeypatch):
    write_package(tmp_path, make_package(),
                  definitions_root=tmp_path / "workspace")
    _seed_env(monkeypatch)


def _mock_versions(payload=None, status_code=200):
    return respx.get(f"{API}/api/business-processes/testbp/versions/").respond(
        json=payload if payload is not None else VERSIONS,
        status_code=status_code,
    )


def _mock_export(slug="testbp", bp_id=1, pkg=None):
    respx.get(f"{API}/api/business-processes/").respond(
        json=[{"id": bp_id, "slug": slug, "name": "Тестовый БП"}],
    )
    data, _ = build_zip(pkg if pkg is not None else make_package())
    return respx.post(f"{API}/api/business-processes/{bp_id}/export/").respond(
        content=data,
    )


DIFF = {
    "task_diff": {
        "added": ["Новая задача"],
        "removed": [],
        "changed": [{"name": "Формирование", "fields": ["description"]}],
    },
    "bp_diff": ["priority_config"],
    "live_impact": {
        "instances": 3, "assignments": 7, "version_number": 4,
        "by_status": {"completed": 3},
    },
    "next_version_number": 5,
    "staged_resources": [{"kind": "catalog_item", "name": "Да/Нет/Может"}],
    "warnings": [{"kind": "catalog_field", "name": "Да/Нет/Поле", "reason": "new"}],
}

VERSIONS = {
    "process": {"id": 1, "slug": "testbp", "name": "Тестовый БП"},
    "versions": [
        {"id": 77, "number": 5, "status": "testing",
         "created_at": None, "promoted_at": None},
        {"id": 40, "number": 4, "status": "published",
         "created_at": None, "promoted_at": None},
    ],
    "testing": {"id": 77, "number": 5},
    "published": {"number": 4},
    "diff": DIFF,
}


# ── ws init ───────────────────────────────────────────────────────────────────

@respx.mock
def test_ws_init_unpacks_export_to_workspace(tmp_path, monkeypatch):
    _seed_workspace(tmp_path, monkeypatch)  # env + перезапишется ниже
    _mock_versions()
    _mock_export()

    runner = CliRunner()
    result = runner.invoke(main, ["ws", "init", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    process_yaml = (tmp_path / "workspace" / "testbp" / "process.yaml")
    assert process_yaml.is_file()
    assert "Тестовый БП" in process_yaml.read_text(encoding="utf-8")
    assert (tmp_path / "workspace" / ".gitignore").is_file()
    assert "задач 2" in result.output


@respx.mock
def test_ws_init_prefers_testing_version(tmp_path, monkeypatch):
    """Живая testing-версия → экспортируется её поколение, не published.

    Иначе воркспейс стартовал бы с published и следующий draft-import
    молча откатил бы несохранённые в published правки (кейс БП 12 из
    слабомодельного прогона 2026-10-19: diff показывал 5 задач, ws init
    выгружал 0).
    """
    _seed_env(monkeypatch)
    _mock_versions()  # VERSIONS: testing №5, published №4
    export = _mock_export()

    runner = CliRunner()
    result = runner.invoke(main, ["ws", "init", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "version=5" in str(export.calls.last.request.url)
    assert "testing-версия №5" in result.output


@respx.mock
def test_ws_init_no_testing_exports_published(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _mock_versions(payload={
        "process": {"id": 1, "slug": "testbp", "name": "Тестовый БП"},
        "versions": [{"id": 40, "number": 4, "status": "published"}],
        "testing": None, "published": {"number": 4}, "diff": None,
    })
    export = _mock_export()

    runner = CliRunner()
    result = runner.invoke(main, ["ws", "init", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "version=" not in str(export.calls.last.request.url)
    assert "testing-версия №" not in result.output


@respx.mock
def test_ws_init_versions_unavailable_falls_back(tmp_path, monkeypatch):
    """Старый сервер без /versions/ (404) — warning и прежний behaviour."""
    _seed_env(monkeypatch)
    _mock_versions(status_code=404)
    export = _mock_export()

    runner = CliRunner()
    result = runner.invoke(main, ["ws", "init", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "Реестр версий недоступен" in result.output
    assert "version=" not in str(export.calls.last.request.url)


@respx.mock
def test_ws_init_no_versions_at_all_exits_2(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _mock_versions(payload={
        "process": {"id": 1, "slug": "testbp", "name": "Тестовый БП"},
        "versions": [], "testing": None, "published": None, "diff": None,
    })

    runner = CliRunner()
    result = runner.invoke(main, ["ws", "init", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 2
    assert "нет ни одной сохранённой версии" in result.output
    assert not (tmp_path / "workspace" / "testbp").exists()


@respx.mock
def test_ws_init_empty_package_warns(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _mock_versions()
    pkg = make_package()
    pkg.business_process.tasks = []
    _mock_export(pkg=pkg)

    runner = CliRunner()
    result = runner.invoke(main, ["ws", "init", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "В пакете 0 задач" in result.output


@respx.mock
def test_ws_init_403_reports_admin_rights(tmp_path, monkeypatch):
    _seed_env(monkeypatch)
    _mock_versions(status_code=403)

    runner = CliRunner()
    result = runner.invoke(main, ["ws", "init", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 1
    assert "нет прав администратора этого БП" in result.output
    assert not (tmp_path / "workspace" / "testbp").exists()


# ── ws check ──────────────────────────────────────────────────────────────────

def test_ws_check_ok(tmp_path):
    write_package(tmp_path, make_package(),
                  definitions_root=tmp_path / "workspace")
    runner = CliRunner()
    result = runner.invoke(main, ["ws", "check"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "testbp" in result.output
    assert "Tier 0" in result.output


def test_ws_check_detects_broken_refs(tmp_path):
    write_package(tmp_path, make_package(),
                  definitions_root=tmp_path / "workspace")
    task_file = (
        tmp_path / "workspace" / "testbp" / "tasks" / "01-formirovanie.yaml"
    )
    task_file.write_text(
        "name: Формирование\nscript_bindings:\n- script_name: ghost\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(main, ["ws", "check", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 1
    assert "ghost" in result.output


def test_ws_check_empty_workspace_hints_init(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["ws", "check"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "ws init" in result.output


def test_ws_check_unknown_slug_exits_2(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["ws", "check", "nope"], obj={"cwd": tmp_path})
    assert result.exit_code == 2
    assert "ws init nope" in result.output


# ── ws test ───────────────────────────────────────────────────────────────────

def _mock_draft_import(status="created", version=5, status_code=201):
    return respx.post(f"{API}/api/business-processes/testbp/draft-import/").respond(
        status_code=status_code,
        json={
            "status": status, "slug": "testbp", "version": version,
            "version_status": "testing", "process_created": False,
            "users_missing": [], "access_policy": "local", "diff": DIFF,
        },
    )


@respx.mock
def test_ws_test_no_run_creates_testing_version(tmp_path, monkeypatch):
    _seed_workspace(tmp_path, monkeypatch)
    route = _mock_draft_import()

    runner = CliRunner()
    result = runner.invoke(
        main, ["ws", "test", "testbp", "--no-run"], obj={"cwd": tmp_path},
    )
    assert result.exit_code == 0, result.output
    assert route.called
    assert "testing-версия №5" in result.output
    assert "Новая задача" in result.output
    assert "live_impact" in result.output
    assert "общие ресурсы" in result.output
    assert "process-instances" not in result.output


@respx.mock
def test_ws_test_idempotent_prints_no_op(tmp_path, monkeypatch):
    _seed_workspace(tmp_path, monkeypatch)
    _mock_draft_import(status="idempotent", version=5, status_code=200)

    runner = CliRunner()
    result = runner.invoke(
        main, ["ws", "test", "testbp", "--no-run"], obj={"cwd": tmp_path},
    )
    assert result.exit_code == 0, result.output
    assert "no-op" in result.output
    assert "payload_hash" in result.output


@respx.mock
def test_ws_test_422_prints_server_errors(tmp_path, monkeypatch):
    _seed_workspace(tmp_path, monkeypatch)
    respx.post(f"{API}/api/business-processes/testbp/draft-import/").respond(
        status_code=422,
        json={"error": "draft_validation_failed",
              "errors": [{"kind": "script_ref", "name": "ghost",
                          "reason": "биндинг — скрипта нет в пакете"}]},
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["ws", "test", "testbp", "--no-run"], obj={"cwd": tmp_path},
    )
    assert result.exit_code == 1
    assert "draft_validation_failed" in result.output
    assert "ghost" in result.output


@respx.mock
def test_ws_test_403_reports_admin_rights(tmp_path, monkeypatch):
    _seed_workspace(tmp_path, monkeypatch)
    respx.post(f"{API}/api/business-processes/testbp/draft-import/").respond(
        status_code=403,
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["ws", "test", "testbp", "--no-run"], obj={"cwd": tmp_path},
    )
    assert result.exit_code == 1
    assert "нет прав администратора этого БП" in result.output


def _mock_test_run(monkeypatch, instance_id=901):
    monkeypatch.setattr(ws_module, "POLL_INTERVAL_SEC", 0.05)
    start_route = respx.post(f"{API}/api/process-instances/").respond(
        status_code=201,
        json={"id": instance_id, "status": "running",
              "source_version_id": 77, "is_test_run": True},
    )
    running = {"run_id": instance_id, "bp_slug": "testbp",
               "status": "running", "assignments": []}
    completed = {
        "run_id": instance_id, "bp_slug": "testbp", "status": "completed",
        "completed_at": "2026-10-18T12:00:00Z",
        "assignments": [
            {"id": 1, "task_slug": "Формирование", "status": "completed",
             "started_at": None, "completed_at": None, "duration_ms": 12,
             "assignee": "admin", "error": None},
            {"id": 2, "task_slug": "Арбитраж", "status": "completed",
             "started_at": None, "completed_at": None, "duration_ms": 3,
             "assignee": "auto", "error": "упс"},
        ],
    }
    respx.get(f"{API}/api/process-instances/{instance_id}/details/").mock(
        side_effect=[
            httpx.Response(200, json=running),
            httpx.Response(200, json=completed),
        ]
    )
    return start_route


@respx.mock
def test_ws_test_runs_and_polls_to_terminal(tmp_path, monkeypatch):
    _seed_workspace(tmp_path, monkeypatch)
    _mock_draft_import()
    respx.get(f"{API}/api/business-processes/testbp/versions/").respond(
        json=VERSIONS,
    )
    start_route = _mock_test_run(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(main, ["ws", "test", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output

    body = json.loads(start_route.calls.last.request.content)
    assert body["business_process"] == 1
    assert body["source_version"] == 77  # PK testing-версии, не номер

    assert "Прогон #901" in result.output
    assert "completed" in result.output
    assert "Формирование" in result.output
    assert "упс" in result.output


@respx.mock
def test_ws_test_input_json_merges_into_start_body(tmp_path, monkeypatch):
    _seed_workspace(tmp_path, monkeypatch)
    _mock_draft_import()
    respx.get(f"{API}/api/business-processes/testbp/versions/").respond(
        json=VERSIONS,
    )
    start_route = _mock_test_run(monkeypatch)
    input_file = tmp_path / "input.json"
    input_file.write_text(
        json.dumps({"name": "Мой прогон", "primary_entity_id": 42}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["ws", "test", "testbp", "--input-json", str(input_file)],
        obj={"cwd": tmp_path},
    )
    assert result.exit_code == 0, result.output

    body = json.loads(start_route.calls.last.request.content)
    assert body["name"] == "Мой прогон"
    assert body["primary_entity_id"] == 42
    assert body["source_version"] == 77


@respx.mock
def test_ws_test_run_timeout_exits_1(tmp_path, monkeypatch):
    _seed_workspace(tmp_path, monkeypatch)
    _mock_draft_import()
    respx.get(f"{API}/api/business-processes/testbp/versions/").respond(
        json=VERSIONS,
    )
    monkeypatch.setattr(ws_module, "POLL_INTERVAL_SEC", 0.05)
    respx.post(f"{API}/api/process-instances/").respond(
        status_code=201,
        json={"id": 901, "status": "running",
              "source_version_id": 77, "is_test_run": True},
    )
    respx.get(f"{API}/api/process-instances/901/details/").respond(
        json={"run_id": 901, "bp_slug": "testbp",
              "status": "running", "assignments": []},
    )

    runner = CliRunner()
    result = runner.invoke(
        main, ["ws", "test", "testbp", "--wait-sec", "1"], obj={"cwd": tmp_path},
    )
    assert result.exit_code == 1
    assert "таймаут" in result.output
    assert "running" in result.output


# ── ws report ─────────────────────────────────────────────────────────────────

@respx.mock
def test_ws_report_renders_diff_and_checklist(tmp_path, monkeypatch):
    _seed_workspace(tmp_path, monkeypatch)
    respx.get(f"{API}/api/business-processes/testbp/versions/").respond(
        json=VERSIONS,
    )

    runner = CliRunner()
    result = runner.invoke(main, ["ws", "report", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "версия №5 — testing" in result.output
    assert "Новая задача" in result.output
    assert "live_impact" in result.output
    assert "экземпляров 3" in result.output
    assert "Применить" in result.output
    assert "только человек" in result.output


@respx.mock
def test_ws_report_without_testing_version(tmp_path, monkeypatch):
    _seed_workspace(tmp_path, monkeypatch)
    registry = dict(VERSIONS)
    registry["testing"] = None
    registry["diff"] = None
    respx.get(f"{API}/api/business-processes/testbp/versions/").respond(
        json=registry,
    )

    runner = CliRunner()
    result = runner.invoke(main, ["ws", "report", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "Testing-версии нет" in result.output


@respx.mock
def test_ws_report_403_reports_admin_rights(tmp_path, monkeypatch):
    _seed_workspace(tmp_path, monkeypatch)
    respx.get(f"{API}/api/business-processes/testbp/versions/").respond(
        status_code=403,
    )

    runner = CliRunner()
    result = runner.invoke(main, ["ws", "report", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 1
    assert "нет прав администратора этого БП" in result.output


# ── ws diff + origin-снапшот (дрилл 2026-10-18) ──────────────────────────────

@respx.mock
def test_ws_init_writes_origin_snapshot(tmp_path, monkeypatch):
    _seed_workspace(tmp_path, monkeypatch)  # env + перезапишется ниже
    _mock_versions()
    _mock_export()

    runner = CliRunner()
    result = runner.invoke(main, ["ws", "init", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    origin = tmp_path / "workspace" / ".ws-origin" / "testbp" / "process.yaml"
    assert origin.is_file()


def test_ws_diff_without_origin_exits_2(tmp_path, monkeypatch):
    _seed_workspace(tmp_path, monkeypatch)

    runner = CliRunner()
    result = runner.invoke(main, ["ws", "diff", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 2
    assert ".ws-origin" in result.output


def test_ws_diff_clean_and_changed(tmp_path, monkeypatch):
    _seed_workspace(tmp_path, monkeypatch)
    write_package(tmp_path, make_package(),
                  definitions_root=tmp_path / "workspace" / ".ws-origin")

    runner = CliRunner()
    # идентично снапшоту — чисто
    result = runner.invoke(main, ["ws", "diff", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "изменений относительно последнего импорта нет" in result.output

    # семантическая правка — unified diff с '+'-строками
    py = tmp_path / "workspace" / "testbp" / "process.yaml"
    text = py.read_text(encoding="utf-8")
    py.write_text(text + "\n# итерация 2\n", encoding="utf-8")
    result = runner.invoke(main, ["ws", "diff", "testbp"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "+# итерация 2" in result.output
    assert "изменённых файлов 1" in result.output
