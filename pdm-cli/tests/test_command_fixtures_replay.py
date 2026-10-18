"""Tests for `pdm fixtures replay` subcommand."""
from pathlib import Path

import pytest
from click.testing import CliRunner

from pdm_cli.cli import main


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "pdm.config.yaml").write_text("""
endpoints:
  sandbox: http://sandbox.local
  hoverfly: http://hoverfly:8888
""", encoding="utf-8")
    (tmp_path / "processes" / "demo-bp").mkdir(parents=True)
    return tmp_path


def test_fixtures_replay_pushes_simulation_to_hoverfly(repo, mocker):
    (repo / "processes/demo-bp/fixtures").mkdir(parents=True, exist_ok=True)
    (repo / "processes/demo-bp/fixtures/http-happy.yaml").write_text("""
name: happy
matchers:
  - request:
      method: GET
      url_matches: 'https://api\\.partner\\.local/v1/ping'
    response:
      status: 200
      body: pong
""", encoding="utf-8")
    put_mock = mocker.patch("pdm_cli.commands.fixtures.HoverflyClient.put_simulation")
    mode_mock = mocker.patch("pdm_cli.commands.fixtures.HoverflyClient.set_mode")
    runner = CliRunner()
    result = runner.invoke(main, ["fixtures", "replay", "--bp", "demo-bp", "--protocol", "http"],
                           obj={"cwd": repo})
    assert result.exit_code == 0, result.output
    assert put_mock.called
    sim = put_mock.call_args[0][0]
    assert len(sim["data"]["pairs"]) == 1
    mode_mock.assert_called_once_with("simulate")


def test_fixtures_replay_dry_run_no_push(repo, mocker):
    (repo / "processes/demo-bp/fixtures").mkdir(parents=True, exist_ok=True)
    (repo / "processes/demo-bp/fixtures/http-happy.yaml").write_text("name: x\nmatchers: []\n", encoding="utf-8")
    put_mock = mocker.patch("pdm_cli.commands.fixtures.HoverflyClient.put_simulation")
    runner = CliRunner()
    r = runner.invoke(main, ["fixtures", "replay", "--bp", "demo-bp", "--protocol", "http", "--dry-run"],
                      obj={"cwd": repo})
    assert r.exit_code == 0
    assert not put_mock.called
