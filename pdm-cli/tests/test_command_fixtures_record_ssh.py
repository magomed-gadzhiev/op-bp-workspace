import json
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
egress:
  ssh:
    redact:
      - regex: 'topsecret'
        replacement: '<redacted>'
""", encoding="utf-8")
    (tmp_path / "processes/demo-bp").mkdir(parents=True)
    (tmp_path / "processes/demo-bp/manifest.yaml").write_text("slug: demo-bp\nname: D\n", encoding="utf-8")
    return tmp_path


def test_record_ssh_from_capture(repo, tmp_path):
    capture = tmp_path / "ssh.jsonl"
    capture.write_text(
        json.dumps({"ts": "2026-05-12", "host": "deploy.local", "user": "deployer",
                    "command": "deploy --password=topsecret", "stdout": "OK\n", "stderr": "", "exit_code": 0,
                    "duration_ms": 100}) + "\n",
        encoding="utf-8")
    runner = CliRunner()
    r = runner.invoke(main, ["fixtures", "record", "--bp", "demo-bp", "--case", "deploy",
                             "--protocol", "ssh", "--ssh-capture", str(capture)],
                      obj={"cwd": repo})
    assert r.exit_code == 0, r.output
    out = repo / "processes/demo-bp/fixtures/ssh-deploy.yaml"
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "topsecret" not in text
    assert "<redacted>" in text


def test_record_ssh_uses_per_bp_capture_dir(repo, tmp_path, monkeypatch):
    captures_root = repo / ".pdm" / "ssh-captures"
    bp_dir = captures_root / "demo-bp"
    bp_dir.mkdir(parents=True)
    (bp_dir / "ssh-capture.jsonl").write_text(
        json.dumps({"ts": "2026-05-12", "bp": "demo-bp", "host": "deploy.local",
                    "user": "deployer", "command": "echo hi",
                    "stdout": "hi\n", "stderr": "", "exit_code": 0,
                    "duration_ms": 1}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("PDM_SSH_CAPTURE_FILE", raising=False)
    runner = CliRunner()
    r = runner.invoke(main, ["fixtures", "record", "--bp", "demo-bp", "--case", "happy",
                             "--protocol", "ssh"],
                      obj={"cwd": repo})
    assert r.exit_code == 0, r.output
    out = repo / "processes/demo-bp/fixtures/ssh-happy.yaml"
    assert out.is_file()


def test_record_ssh_stamps_version_and_recorded_at(repo, tmp_path):
    """E16 US1 — SSH record stamps version=1 + recorded_at (FR-002 uniform)."""
    from pdm_cli.fixtures.ssh import load_ssh_fixture

    capture = tmp_path / "ssh.jsonl"
    capture.write_text(
        json.dumps({"ts": "2026-05-12", "host": "deploy.local", "user": "deployer",
                    "command": "echo hi", "stdout": "hi\n", "stderr": "", "exit_code": 0,
                    "duration_ms": 1}) + "\n",
        encoding="utf-8")
    r = CliRunner().invoke(main, ["fixtures", "record", "--bp", "demo-bp", "--case", "stamp",
                                  "--protocol", "ssh", "--ssh-capture", str(capture)],
                           obj={"cwd": repo})
    assert r.exit_code == 0, r.output
    fix = load_ssh_fixture(repo / "processes/demo-bp/fixtures/ssh-stamp.yaml")
    assert fix.version == 1
    assert fix.recorded_at is not None and fix.recorded_at.endswith("Z")
