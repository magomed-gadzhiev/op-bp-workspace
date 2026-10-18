"""Tests for `pdm test` CLI command.

We monkeypatch:
  - `pdm_cli.commands.test_cmd.ensure_sandbox_up` / `bring_up_sandbox` /
    `bring_down_sandbox` to avoid touching docker.
  - `pdm_cli.commands.test_cmd.run_case` to return canned CaseResult objects.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pdm_cli.cli import main
from pdm_cli.sandbox_lifecycle import SandboxNotRunningError
from pdm_cli.test_runner.runner import AssertionResult, CaseResult


def _write_config(repo: Path) -> None:
    (repo / "pdm.config.yaml").write_text(
        "endpoints:\n"
        "  sandbox: http://pdm-sandbox:8000\n"
        "api_keys:\n"
        "  sandbox: T\n",
        encoding="utf-8",
    )
    (repo / ".pdm").mkdir(exist_ok=True)
    (repo / ".pdm" / "secrets.yaml").write_text(
        "api_key_sandbox: T\n", encoding="utf-8",
    )


def _write_bp(repo: Path, slug: str = "bp1", case_name: str = "smoke") -> None:
    bp = repo / "processes" / slug / "tests"
    bp.mkdir(parents=True, exist_ok=True)
    (repo / "processes" / slug / "manifest.yaml").write_text(
        f"slug: {slug}\nname: BP1\nversion: 1\nstatus: draft\n",
        encoding="utf-8",
    )
    (bp / f"{case_name}.yaml").write_text(
        f"name: {case_name}\n"
        "fixtures: []\n"
        "entity:\n"
        "  type: contract\n"
        "  fields: {}\n"
        "expect:\n"
        "  final_status: completed\n"
        "  side_effects: []\n",
        encoding="utf-8",
    )


@pytest.fixture
def repo(tmp_path):
    _write_config(tmp_path)
    _write_bp(tmp_path)
    return tmp_path


def _passing_result(tc, bp_slug, ctx):
    return CaseResult(
        bp=bp_slug, case=tc.name, run_id="42",
        status="passed", process_status="completed",
    )


def _failing_result(tc, bp_slug, ctx):
    return CaseResult(
        bp=bp_slug, case=tc.name, run_id="42",
        status="failed", process_status="completed",
        assertions=[AssertionResult(
            index=0, kind="http", status="failed",
            expected=">=1", got=0, explain="no matches",
        )],
    )


def test_pdm_test_runs_all_cases(repo, monkeypatch):
    monkeypatch.setattr("pdm_cli.commands.test_cmd.ensure_sandbox_up",
                        lambda: None)
    monkeypatch.setattr("pdm_cli.commands.test_cmd.run_case",
                        _passing_result)

    runner = CliRunner()
    r = runner.invoke(main, ["test"], obj={"cwd": repo})
    assert r.exit_code == 0, r.output
    assert "passed" in r.output

    last = json.loads(
        (repo / ".pdm" / "last-run.json").read_text(encoding="utf-8")
    )
    assert "started_at" in last
    assert len(last["cases"]) == 1
    case = last["cases"][0]
    assert case["bp"] == "bp1"
    assert case["case"] == "smoke"
    assert case["status"] == "passed"
    assert case["run_id"] == "42"
    assert case["process_status"] == "completed"
    assert case["assertions"] == []


def test_pdm_test_exits_2_when_sandbox_not_running(repo, monkeypatch):
    def _raise():
        raise SandboxNotRunningError("Sandbox is not running")
    monkeypatch.setattr("pdm_cli.commands.test_cmd.ensure_sandbox_up", _raise)
    # run_case must NOT be called; raise loudly if it is.
    monkeypatch.setattr(
        "pdm_cli.commands.test_cmd.run_case",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("run_case must not be called when sandbox is down")
        ),
    )
    runner = CliRunner()
    r = runner.invoke(main, ["test"], obj={"cwd": repo})
    assert r.exit_code == 2, r.output
    assert "Sandbox is not running" in r.output


def test_pdm_test_exits_1_on_failed_case(repo, monkeypatch):
    monkeypatch.setattr("pdm_cli.commands.test_cmd.ensure_sandbox_up",
                        lambda: None)
    monkeypatch.setattr("pdm_cli.commands.test_cmd.run_case",
                        _failing_result)

    runner = CliRunner()
    r = runner.invoke(main, ["test"], obj={"cwd": repo})
    assert r.exit_code == 1, r.output


def test_pdm_test_exits_2_on_runner_error(repo, monkeypatch):
    monkeypatch.setattr("pdm_cli.commands.test_cmd.ensure_sandbox_up",
                        lambda: None)

    def _error_result(tc, bp_slug, ctx):
        return CaseResult(
            bp=bp_slug, case=tc.name, run_id=None,
            status="error", error="boom",
        )
    monkeypatch.setattr("pdm_cli.commands.test_cmd.run_case", _error_result)

    runner = CliRunner()
    r = runner.invoke(main, ["test"], obj={"cwd": repo})
    assert r.exit_code == 2, r.output


def test_pdm_test_writes_last_run_json_shape(repo, monkeypatch):
    monkeypatch.setattr("pdm_cli.commands.test_cmd.ensure_sandbox_up",
                        lambda: None)
    monkeypatch.setattr("pdm_cli.commands.test_cmd.run_case",
                        _failing_result)

    runner = CliRunner()
    runner.invoke(main, ["test"], obj={"cwd": repo})

    last = json.loads(
        (repo / ".pdm" / "last-run.json").read_text(encoding="utf-8")
    )
    assert set(last.keys()) == {"started_at", "cases"}
    case = last["cases"][0]
    assert set(case.keys()) >= {
        "bp", "case", "run_id", "status", "process_status",
        "error", "assertions",
    }
    assert len(case["assertions"]) == 1
    a = case["assertions"][0]
    assert a["kind"] == "http"
    assert a["status"] == "failed"
    assert a["expected"] == ">=1"
    assert a["got"] == 0


def test_pdm_test_filters_by_bp(tmp_path, monkeypatch):
    _write_config(tmp_path)
    _write_bp(tmp_path, slug="bp1")
    _write_bp(tmp_path, slug="bp2")

    monkeypatch.setattr("pdm_cli.commands.test_cmd.ensure_sandbox_up",
                        lambda: None)
    monkeypatch.setattr("pdm_cli.commands.test_cmd.run_case",
                        _passing_result)

    runner = CliRunner()
    r = runner.invoke(main, ["test", "--bp", "bp1"], obj={"cwd": tmp_path})
    assert r.exit_code == 0, r.output

    last = json.loads(
        (tmp_path / ".pdm" / "last-run.json").read_text(encoding="utf-8")
    )
    assert len(last["cases"]) == 1
    assert last["cases"][0]["bp"] == "bp1"


def test_pdm_test_filters_by_case(tmp_path, monkeypatch):
    _write_config(tmp_path)
    _write_bp(tmp_path, slug="bp1", case_name="smoke")
    _write_bp(tmp_path, slug="bp1", case_name="happy")

    monkeypatch.setattr("pdm_cli.commands.test_cmd.ensure_sandbox_up",
                        lambda: None)
    monkeypatch.setattr("pdm_cli.commands.test_cmd.run_case",
                        _passing_result)

    runner = CliRunner()
    r = runner.invoke(
        main, ["test", "--case", "smoke"], obj={"cwd": tmp_path},
    )
    assert r.exit_code == 0, r.output
    last = json.loads(
        (tmp_path / ".pdm" / "last-run.json").read_text(encoding="utf-8")
    )
    assert len(last["cases"]) == 1
    assert last["cases"][0]["case"] == "smoke"


def test_pdm_test_ephemeral_brings_up_and_down(repo, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "pdm_cli.commands.test_cmd.bring_up_sandbox",
        lambda: calls.append("up"),
    )
    monkeypatch.setattr(
        "pdm_cli.commands.test_cmd.bring_down_sandbox",
        lambda: calls.append("down"),
    )
    monkeypatch.setattr(
        "pdm_cli.commands.test_cmd.ensure_sandbox_up",
        lambda: (_ for _ in ()).throw(
            AssertionError("must not call ensure_sandbox_up in --ephemeral")
        ),
    )
    monkeypatch.setattr("pdm_cli.commands.test_cmd.run_case",
                        _passing_result)

    runner = CliRunner()
    r = runner.invoke(main, ["test", "--ephemeral"], obj={"cwd": repo})
    assert r.exit_code == 0, r.output
    assert calls == ["up", "down"]


def test_pdm_test_handles_malformed_yaml(tmp_path, monkeypatch):
    """Malformed YAML for one case should produce status=error and not
    abort sibling cases. last-run.json must still be written."""
    _write_config(tmp_path)
    # Good BP/case
    _write_bp(tmp_path, slug="bp1", case_name="ok")
    # Bad case: schema-invalid YAML (missing required 'expect')
    bad_dir = tmp_path / "processes" / "bp2" / "tests"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "processes" / "bp2" / "manifest.yaml").write_text(
        "slug: bp2\nname: BP2\nversion: 1\nstatus: draft\n",
        encoding="utf-8",
    )
    (bad_dir / "broken.yaml").write_text(
        "name: broken\nentity_id: 1\n",  # missing required 'expect'
        encoding="utf-8",
    )

    monkeypatch.setattr("pdm_cli.commands.test_cmd.ensure_sandbox_up",
                        lambda: None)
    monkeypatch.setattr("pdm_cli.commands.test_cmd.run_case",
                        _passing_result)

    runner = CliRunner()
    r = runner.invoke(main, ["test"], obj={"cwd": tmp_path})
    # has_error → exit 2
    assert r.exit_code == 2, r.output

    last = json.loads(
        (tmp_path / ".pdm" / "last-run.json").read_text(encoding="utf-8")
    )
    by_bp = {(c["bp"], c["case"]): c for c in last["cases"]}
    assert ("bp1", "ok") in by_bp
    assert by_bp[("bp1", "ok")]["status"] == "passed"
    assert ("bp2", "broken") in by_bp
    bad = by_bp[("bp2", "broken")]
    assert bad["status"] == "error"
    assert "load_test_case failed" in (bad["error"] or "")
    assert bad["run_id"] is None


def test_pdm_test_ephemeral_tears_down_on_runner_exception(repo, monkeypatch):
    """If run_case raises mid-loop in --ephemeral mode, sandbox must still be
    torn down via finally."""
    calls = []
    monkeypatch.setattr(
        "pdm_cli.commands.test_cmd.bring_up_sandbox",
        lambda: calls.append("up"),
    )
    monkeypatch.setattr(
        "pdm_cli.commands.test_cmd.bring_down_sandbox",
        lambda: calls.append("down"),
    )

    def _boom(tc, bp_slug, ctx):
        raise RuntimeError("runner exploded")
    monkeypatch.setattr("pdm_cli.commands.test_cmd.run_case", _boom)

    runner = CliRunner()
    r = runner.invoke(main, ["test", "--ephemeral"], obj={"cwd": repo})
    # The exception will propagate to click; what we care about is that
    # bring_down_sandbox was still invoked.
    assert "down" in calls, (calls, r.output)


def test_pdm_test_loads_fixtures_before_run_case(tmp_path, monkeypatch):
    """Non-empty `fixtures:` triggers actual fixture loading (Etap 11)."""
    _write_config(tmp_path)
    bp = tmp_path / "processes" / "bp1" / "tests"
    bp.mkdir(parents=True, exist_ok=True)
    (tmp_path / "processes" / "bp1" / "manifest.yaml").write_text(
        "slug: bp1\nname: BP1\nversion: 1\nstatus: draft\n",
        encoding="utf-8",
    )
    (bp / "with_fix.yaml").write_text(
        "name: with_fix\n"
        "fixtures: [http-orders]\n"
        "entity:\n"
        "  type: contract\n"
        "  fields: {}\n"
        "expect:\n"
        "  final_status: completed\n"
        "  side_effects: []\n",
        encoding="utf-8",
    )
    fixtures_dir = tmp_path / "processes" / "bp1" / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "http-orders.yaml").write_text(
        "name: http-orders\nmatchers: []\n", encoding="utf-8"
    )

    monkeypatch.setattr("pdm_cli.commands.test_cmd.ensure_sandbox_up",
                        lambda: None)
    monkeypatch.setattr("pdm_cli.commands.test_cmd.run_case",
                        _passing_result)

    load_calls = []

    def fake_load(tc, bp_dir, ctx):
        load_calls.append(tc.fixtures)
        return tc.fixtures

    monkeypatch.setattr("pdm_cli.fixtures.loader.load_fixtures_for_case", fake_load)
    monkeypatch.setattr("pdm_cli.fixtures.loader.unload_fixtures_for_case", lambda *a: None)

    runner = CliRunner()
    r = runner.invoke(main, ["test"], obj={"cwd": tmp_path})
    assert r.exit_code == 0, r.output
    assert load_calls, "load_fixtures_for_case should have been called"


def test_pdm_test_ephemeral_with_keep_does_not_tear_down(repo, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "pdm_cli.commands.test_cmd.bring_up_sandbox",
        lambda: calls.append("up"),
    )
    monkeypatch.setattr(
        "pdm_cli.commands.test_cmd.bring_down_sandbox",
        lambda: calls.append("down"),
    )
    monkeypatch.setattr("pdm_cli.commands.test_cmd.ensure_sandbox_up",
                        lambda: None)
    monkeypatch.setattr("pdm_cli.commands.test_cmd.run_case",
                        _passing_result)

    runner = CliRunner()
    r = runner.invoke(
        main, ["test", "--ephemeral", "--keep"], obj={"cwd": repo},
    )
    assert r.exit_code == 0, r.output
    assert calls == ["up"]
