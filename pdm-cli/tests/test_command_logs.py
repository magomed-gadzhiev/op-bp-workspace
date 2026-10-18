"""Tests for `pdm logs <run_id>` CLI command.

We mock:
  - httpx via respx for both the PDM process-instance API and the
    Hoverfly / ssh-replay journal endpoints;
  - `subprocess.run` (via monkeypatch) for `docker compose logs` calls so the
    tests do not touch real Docker.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import respx
from click.testing import CliRunner

from pdm_cli.cli import main


SB = "http://pdm-sandbox:8000"
HOVERFLY = "http://hoverfly:8888"
SSH_REPLAY = "http://ssh-replay:8889"


def _write_config(repo: Path) -> None:
    (repo / "pdm.config.yaml").write_text(
        "endpoints:\n"
        f"  sandbox: {SB}\n"
        f"hoverfly_admin: {HOVERFLY}\n"
        f"ssh_replay_journal: {SSH_REPLAY}\n"
        "api_keys:\n"
        "  sandbox: T\n",
        encoding="utf-8",
    )
    (repo / ".pdm").mkdir(exist_ok=True)
    (repo / ".pdm" / "secrets.yaml").write_text(
        "api_key_sandbox: T\n", encoding="utf-8",
    )


def _write_last_run(repo: Path, run_id: str = "42") -> None:
    (repo / ".pdm").mkdir(exist_ok=True)
    (repo / ".pdm" / "last-run.json").write_text(
        json.dumps({
            "started_at": "2026-05-13T10:00:00Z",
            "cases": [{
                "bp": "bp1",
                "case": "smoke",
                "run_id": run_id,
                "status": "passed",
                "process_status": "completed",
                "error": "",
                "assertions": [],
            }],
        }),
        encoding="utf-8",
    )


def _patch_docker_logs(monkeypatch, marker: str = "container-log") -> list[list[str]]:
    """Replace subprocess.run with a stub that records invocations.

    Returns a list that will be populated with the command argv of every call.
    """
    captured: list[list[str]] = []
    real_run = subprocess.run

    def _fake_run(cmd, *args, **kwargs):  # noqa: ANN001
        # Only intercept docker compose logs calls; pass through everything else.
        if (
            isinstance(cmd, list)
            and len(cmd) >= 2
            and cmd[0] == "docker"
            and "logs" in cmd
        ):
            captured.append(list(cmd))
            return SimpleNamespace(
                stdout=f"{marker} for {cmd[-1]}\n",
                stderr="",
                returncode=0,
            )
        return real_run(cmd, *args, **kwargs)  # pragma: no cover

    monkeypatch.setattr(
        "pdm_cli.commands.logs.subprocess.run", _fake_run,
    )
    return captured


@respx.mock
def test_logs_for_last_run_includes_journals(tmp_path, monkeypatch):
    _write_config(tmp_path)
    _write_last_run(tmp_path, run_id="42")

    respx.get(f"{SB}/api/process-instances/42/").respond(
        json={"id": 42, "status": "completed", "bp": "bp1"},
    )
    respx.get(f"{HOVERFLY}/api/v2/journal").respond(
        json={"journal": [
            {"request": {"method": "GET", "destination": "x", "path": "/y"},
             "response": {"status": 200}},
        ]},
    )
    respx.get(f"{SSH_REPLAY}/journal").respond(
        json=[{"host": "host-1", "command": "ls /"}],
    )
    captured = _patch_docker_logs(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        main, ["logs", "42", "--format", "json"],
        obj={"cwd": tmp_path},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["run_id"] == "42"
    assert payload["is_last_run"] is True
    assert payload["bp"] == "bp1"
    assert payload["case"] == "smoke"
    # All four sources present
    assert payload["process_instance"]["id"] == 42
    assert isinstance(payload["egress"]["http"], list)
    assert len(payload["egress"]["http"]) == 1
    assert isinstance(payload["egress"]["ssh"], list)
    assert payload["egress"]["ssh"][0]["host"] == "host-1"
    assert "containers" in payload and payload["containers"]
    # docker compose logs invoked for every required service
    assert len(captured) >= 1
    services_called = {cmd[-1] for cmd in captured}
    assert "pdm-backend-sandbox" in services_called


@respx.mock
def test_logs_for_old_run_marks_journal_cleared(tmp_path, monkeypatch):
    _write_config(tmp_path)
    # last-run has a *different* run_id → request run_id=42 is "old"
    _write_last_run(tmp_path, run_id="99")

    respx.get(f"{SB}/api/process-instances/42/").respond(
        json={"id": 42, "status": "completed"},
    )
    _patch_docker_logs(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        main, ["logs", "42", "--format", "json"],
        obj={"cwd": tmp_path},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["run_id"] == "42"
    assert payload["is_last_run"] is False
    # Journals are replaced with the "cleared" marker, not fetched.
    assert isinstance(payload["egress"]["http"], dict)
    assert "journal cleared" in payload["egress"]["http"]["note"]
    assert isinstance(payload["egress"]["ssh"], dict)
    assert "journal cleared" in payload["egress"]["ssh"]["note"]
    # process_instance still fetched from API
    assert payload["process_instance"]["id"] == 42


@respx.mock
def test_logs_unknown_run_exits_3(tmp_path, monkeypatch):
    _write_config(tmp_path)
    # No last-run.json on disk → no matching case
    respx.get(f"{SB}/api/process-instances/777/").respond(
        status_code=404, json={"detail": "not found"},
    )
    _patch_docker_logs(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        main, ["logs", "777", "--format", "json"],
        obj={"cwd": tmp_path},
    )

    assert result.exit_code == 3, result.output
    payload = json.loads(result.stdout)
    assert payload["error"] == "run_id not found"
    assert payload["run_id"] == "777"


@respx.mock
def test_logs_text_format_renders_summary(tmp_path, monkeypatch):
    """Sanity check: --format text emits a human-readable summary."""
    _write_config(tmp_path)
    _write_last_run(tmp_path, run_id="42")
    respx.get(f"{SB}/api/process-instances/42/").respond(
        json={"id": 42, "status": "completed"},
    )
    respx.get(f"{HOVERFLY}/api/v2/journal").respond(json={"journal": []})
    respx.get(f"{SSH_REPLAY}/journal").respond(json=[])
    _patch_docker_logs(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(
        main, ["logs", "42", "--format", "text"],
        obj={"cwd": tmp_path},
    )

    assert result.exit_code == 0, result.output
    assert "run_id: 42" in result.output
    assert "is_last_run=True" in result.output
    assert "bp1/smoke" in result.output
    assert "egress.http" in result.output
    assert "containers" in result.output
