"""Tests for per-case fixture auto-loading integration in `pdm test` command."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from click.testing import CliRunner

from pdm_cli.commands.test_cmd import test


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "pdm.config.yaml").write_text(
        "endpoints:\n  sandbox: http://sandbox.local\nhoverfly_admin: http://hf:8888\n"
        "ssh_replay_journal: http://ssh:9080\nsandbox_db_dsn: postgresql://x\n",
        encoding="utf-8",
    )
    (tmp_path / ".pdm").mkdir()
    (tmp_path / ".pdm" / "secrets.yaml").write_text(
        "api_key_sandbox: key\n", encoding="utf-8"
    )
    proc = tmp_path / "processes" / "order-flow"
    proc.mkdir(parents=True)
    tests_dir = proc / "tests"
    tests_dir.mkdir()
    case_file = tests_dir / "happy-path.yaml"
    case_file.write_text(
        "name: happy-path\nfixtures: [http-orders]\n"
        "entity_id: 1\n"
        "expect:\n  final_status: completed\n  side_effects: []\n",
        encoding="utf-8",
    )
    (proc / "fixtures").mkdir()
    (proc / "fixtures" / "http-orders.yaml").write_text(
        "name: http-orders\nmatchers: []\n", encoding="utf-8"
    )
    return tmp_path


def _mock_runner_ctx():
    ctx = MagicMock()
    ctx.hoverfly_admin = "http://hf:8888"
    ctx.ssh_override_dir = ""
    return ctx


def test_fixture_loaded_before_run_case(repo):
    """load_fixtures_for_case is called before run_case."""
    call_order = []

    def fake_load(tc, bp_dir, ctx):
        call_order.append("load")
        return ["http-orders"]

    def fake_run(tc, bp_slug, ctx):
        call_order.append("run")
        from pdm_cli.test_runner.runner import CaseResult
        return CaseResult(bp=bp_slug, case=tc.name, run_id="r1", status="passed")

    def fake_unload(loaded, ctx):
        call_order.append("unload")

    with patch("pdm_cli.commands.test_cmd.ensure_sandbox_up"), \
         patch("pdm_cli.commands.test_cmd.RunnerContext") as mock_rc_cls, \
         patch("pdm_cli.commands.test_cmd.run_case", side_effect=fake_run), \
         patch("pdm_cli.fixtures.loader.load_fixtures_for_case", side_effect=fake_load), \
         patch("pdm_cli.fixtures.loader.unload_fixtures_for_case", side_effect=fake_unload):

        mock_rc_cls.return_value = _mock_runner_ctx()
        runner = CliRunner()
        runner.invoke(test, ["--bp", "order-flow", "--case", "happy-path"],
                      obj={"cwd": str(repo)})

    assert call_order.index("load") < call_order.index("run")


def test_fixture_runtime_error_sets_case_error_and_continues(repo):
    """RuntimeError from load_fixtures_for_case → CaseResult(status='error'), suite continues."""
    def fake_load(tc, bp_dir, ctx):
        raise RuntimeError("fixture file not found")

    mock_run = MagicMock()

    with patch("pdm_cli.commands.test_cmd.ensure_sandbox_up"), \
         patch("pdm_cli.commands.test_cmd.RunnerContext") as mock_rc_cls, \
         patch("pdm_cli.commands.test_cmd.run_case", mock_run), \
         patch("pdm_cli.fixtures.loader.load_fixtures_for_case", side_effect=fake_load):

        mock_rc_cls.return_value = _mock_runner_ctx()
        runner = CliRunner()
        result = runner.invoke(test, ["--bp", "order-flow", "--case", "happy-path"],
                               obj={"cwd": str(repo)})

    mock_run.assert_not_called()
    last_run = (repo / ".pdm" / "last-run.json").read_text(encoding="utf-8")
    import json
    data = json.loads(last_run)
    assert any(c["status"] == "error" for c in data["cases"])


def test_unload_called_after_failed_case(repo):
    """unload_fixtures_for_case is called even when run_case raises."""
    unload_calls = []

    def fake_load(tc, bp_dir, ctx):
        return ["http-orders"]

    def fake_run(tc, bp_slug, ctx):
        raise RuntimeError("unexpected crash")

    def fake_unload(loaded, ctx):
        unload_calls.append(loaded)

    with patch("pdm_cli.commands.test_cmd.ensure_sandbox_up"), \
         patch("pdm_cli.commands.test_cmd.RunnerContext") as mock_rc_cls, \
         patch("pdm_cli.commands.test_cmd.run_case", side_effect=fake_run), \
         patch("pdm_cli.fixtures.loader.load_fixtures_for_case", side_effect=fake_load), \
         patch("pdm_cli.fixtures.loader.unload_fixtures_for_case", side_effect=fake_unload):

        mock_rc_cls.return_value = _mock_runner_ctx()
        runner = CliRunner()
        runner.invoke(test, ["--bp", "order-flow", "--case", "happy-path"],
                      obj={"cwd": str(repo)}, catch_exceptions=True)

    assert unload_calls, "unload_fixtures_for_case must be called even when run_case raises"
