"""E16 US3 — `pdm fixtures refresh` re-captures with diff / archive / increment.

Covers contracts C-R1 … C-R8 (specs/036-fixture-hygiene/contracts/fixtures-refresh.md).
Seeds the active fixture with `record` so content equality flows through the same
serializer (the only reliable way to exercise the "no changes" no-op).
"""
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pdm_cli.cli import main
from pdm_cli.fixtures.http import load_http_fixture
from pdm_cli.fixtures.ssh import load_ssh_fixture
from pdm_cli.fixtures.versioning import resolve_fixture_file


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "pdm.config.yaml").write_text(
        "endpoints:\n  sandbox: http://x\n  hoverfly: http://hoverfly:8888\n",
        encoding="utf-8",
    )
    bp = tmp_path / "processes" / "demo-bp"
    bp.mkdir(parents=True)
    (bp / "manifest.yaml").write_text(
        "slug: demo-bp\nname: D\nversion: 1\nstatus: draft\n", encoding="utf-8"
    )
    return tmp_path


def _sim(status: int, body: str) -> dict:
    return {
        "data": {"pairs": [{
            "request": {"method": [{"matcher": "exact", "value": "GET"}],
                        "destination": [{"matcher": "exact", "value": "x.local"}],
                        "path": [{"matcher": "exact", "value": "/"}],
                        "scheme": [{"matcher": "exact", "value": "http"}]},
            "response": {"status": status, "body": body, "headers": {}}
        }]},
        "meta": {"schemaVersion": "v5.2"},
    }


def _sim_file(tmp_path: Path, name: str, status: int, body: str) -> str:
    p = tmp_path / name
    p.write_text(json.dumps(_sim(status, body)), encoding="utf-8")
    return str(p)


def _record_http(repo: Path, case: str, sim_file: str) -> None:
    r = CliRunner().invoke(main, ["fixtures", "record", "--bp", "demo-bp", "--case", case,
                                  "--protocol", "http", "--from-file", sim_file],
                           obj={"cwd": repo})
    assert r.exit_code == 0, r.output


def _refresh(repo: Path, *args) -> object:
    return CliRunner().invoke(
        main, ["fixtures", "refresh", "--bp", "demo-bp", *args], obj={"cwd": repo}
    )


def test_refresh_shows_content_diff_ignoring_metadata(repo, tmp_path):  # C-R2
    _record_http(repo, "happy", _sim_file(tmp_path, "s1.json", 200, "ok"))
    new_sim = _sim_file(tmp_path, "s2.json", 201, "ok")
    r = _refresh(repo, "--case", "happy", "--protocol", "http",
                 "--from-file", new_sim, "--dry-run")
    assert r.exit_code == 0, r.output
    assert "201" in r.output  # changed content shown
    assert "recorded_at" not in r.output  # metadata excluded from the diff


def test_refresh_apply_archives_and_increments(repo, tmp_path):  # C-R3
    _record_http(repo, "happy", _sim_file(tmp_path, "s1.json", 200, "ok"))
    new_sim = _sim_file(tmp_path, "s2.json", 201, "ok")
    r = _refresh(repo, "--case", "happy", "--protocol", "http", "--from-file", new_sim)
    assert r.exit_code == 0, r.output
    active = repo / "processes/demo-bp/fixtures/http-happy.yaml"
    fix = load_http_fixture(active)
    assert fix.version == 2
    assert fix.recorded_at is not None
    archived = repo / "processes/demo-bp/fixtures/_archive/http-happy/v1.yaml"
    assert archived.is_file()
    assert "200" in archived.read_text(encoding="utf-8")  # frozen old content


def test_refresh_dry_run_writes_nothing(repo, tmp_path):  # C-R4
    _record_http(repo, "happy", _sim_file(tmp_path, "s1.json", 200, "ok"))
    new_sim = _sim_file(tmp_path, "s2.json", 201, "ok")
    r = _refresh(repo, "--case", "happy", "--protocol", "http",
                 "--from-file", new_sim, "--dry-run")
    assert r.exit_code == 0, r.output
    fix = load_http_fixture(repo / "processes/demo-bp/fixtures/http-happy.yaml")
    assert fix.version == 1  # not incremented
    assert not (repo / "processes/demo-bp/fixtures/_archive/http-happy").exists()


def test_refresh_identical_capture_is_noop(repo, tmp_path):  # C-R5
    sim = _sim_file(tmp_path, "s1.json", 200, "ok")
    _record_http(repo, "happy", sim)
    r = _refresh(repo, "--case", "happy", "--protocol", "http", "--from-file", sim)
    assert r.exit_code == 0, r.output
    assert "no changes" in r.output.lower()
    fix = load_http_fixture(repo / "processes/demo-bp/fixtures/http-happy.yaml")
    assert fix.version == 1  # no increment
    assert not (repo / "processes/demo-bp/fixtures/_archive/http-happy").exists()  # no archive


def test_refresh_pin_still_loads_archived_after_refresh(repo, tmp_path):  # C-R6 / SC-005
    _record_http(repo, "happy", _sim_file(tmp_path, "s1.json", 200, "old-body"))
    _refresh(repo, "--case", "happy", "--protocol", "http",
             "--from-file", _sim_file(tmp_path, "s2.json", 200, "new-body"))
    bp_dir = repo / "processes" / "demo-bp"
    pinned = resolve_fixture_file(bp_dir, "http-happy@1")
    assert "old-body" in pinned.read_text(encoding="utf-8")


def test_refresh_missing_fixture_clear_message(repo, tmp_path):  # C-R7
    r = _refresh(repo, "--case", "ghost", "--protocol", "http",
                 "--from-file", _sim_file(tmp_path, "s.json", 200, "ok"))
    assert r.exit_code == 0
    assert "Traceback" not in r.output
    assert "no" in r.output.lower()  # "no existing fixture" / similar


def test_refresh_nonexistent_bp_clear_message(tmp_path):  # C-R7 (bad BP)
    (tmp_path / "pdm.config.yaml").write_text("endpoints:\n  sandbox: http://x\n", encoding="utf-8")
    r = CliRunner().invoke(main, ["fixtures", "refresh", "--bp", "ghost", "--case", "x",
                                  "--protocol", "http"], obj={"cwd": tmp_path})
    assert r.exit_code == 0
    assert "Traceback" not in r.output


def test_refresh_protocol_all_http_and_ssh(repo, tmp_path):  # C-R8
    # Seed http via record + ssh via record (from a capture file).
    _record_http(repo, "happy", _sim_file(tmp_path, "s1.json", 200, "ok"))
    cap1 = tmp_path / "c1.jsonl"
    cap1.write_text(json.dumps({"host": "h", "user": "u", "command": "echo 1",
                                "stdout": "one\n", "stderr": "", "exit_code": 0,
                                "duration_ms": 1}) + "\n", encoding="utf-8")
    r = CliRunner().invoke(main, ["fixtures", "record", "--bp", "demo-bp", "--case", "happy",
                                  "--protocol", "ssh", "--ssh-capture", str(cap1)],
                           obj={"cwd": repo})
    assert r.exit_code == 0, r.output

    # Refresh both protocols with changed content.
    new_sim = _sim_file(tmp_path, "s2.json", 201, "ok")
    cap2 = tmp_path / "c2.jsonl"
    cap2.write_text(json.dumps({"host": "h", "user": "u", "command": "echo 2",
                                "stdout": "two\n", "stderr": "", "exit_code": 0,
                                "duration_ms": 1}) + "\n", encoding="utf-8")
    r = _refresh(repo, "--case", "happy", "--protocol", "all",
                 "--from-file", new_sim, "--ssh-capture", str(cap2))
    assert r.exit_code == 0, r.output
    assert load_http_fixture(repo / "processes/demo-bp/fixtures/http-happy.yaml").version == 2
    assert load_ssh_fixture(repo / "processes/demo-bp/fixtures/ssh-happy.yaml").version == 2
