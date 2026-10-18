from pathlib import Path
from click.testing import CliRunner
import pytest
from pdm_cli.cli import main


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "pdm.config.yaml").write_text("""
endpoints:
  sandbox: http://sandbox.local
  hoverfly: http://hoverfly:8888
""", encoding="utf-8")
    (tmp_path / "processes/bp1/fixtures").mkdir(parents=True)
    (tmp_path / "processes/bp1/fixtures/ssh-a.yaml").write_text("name: a\nmatchers: []\n", encoding="utf-8")
    (tmp_path / "processes/bp2/fixtures").mkdir(parents=True)
    (tmp_path / "processes/bp2/fixtures/ssh-b.yaml").write_text("name: b\nmatchers: []\n", encoding="utf-8")
    return tmp_path


def test_replay_ssh_consolidates(repo, tmp_path, monkeypatch):
    target = tmp_path / "ssh-replay-fixtures"
    monkeypatch.setenv("PDM_SSH_REPLAY_DIR", str(target))
    runner = CliRunner()
    r = runner.invoke(main, ["fixtures","replay","--protocol","ssh"], obj={"cwd": repo})
    assert r.exit_code == 0, r.output
    assert (target / "ssh-a.yaml").is_file()
    assert (target / "ssh-b.yaml").is_file()
