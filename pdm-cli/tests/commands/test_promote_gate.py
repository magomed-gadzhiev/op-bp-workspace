"""Tests for _run_promote_gate: validate fail, last-run failures, --skip-gate, clean state."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from pdm_cli.commands.promote import _run_promote_gate


@pytest.fixture
def clean_repo(tmp_path):
    (tmp_path / ".pdm").mkdir()
    return tmp_path


def test_gate_aborts_when_validate_fails(clean_repo):
    """If pdm validate exits non-zero, gate raises ClickException."""
    fake_result = MagicMock()
    fake_result.exit_code = 1
    fake_result.output = "schema error in process foo"

    with patch("pdm_cli.commands.promote.CliRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner.invoke.return_value = fake_result
        mock_runner_cls.return_value = mock_runner

        with pytest.raises(click.ClickException, match="pdm validate failed"):
            _run_promote_gate(clean_repo, {})


def test_gate_aborts_when_last_run_has_failures(clean_repo):
    """If .pdm/last-run.json has failed cases, gate raises ClickException."""
    (clean_repo / ".pdm" / "last-run.json").write_text(
        json.dumps({
            "cases": [
                {"bp": "order-flow", "case": "happy-path", "status": "failed"},
                {"bp": "order-flow", "case": "timeout-case", "status": "timeout"},
            ]
        }),
        encoding="utf-8",
    )

    fake_result = MagicMock()
    fake_result.exit_code = 0
    fake_result.output = "OK"

    with patch("pdm_cli.commands.promote.CliRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner.invoke.return_value = fake_result
        mock_runner_cls.return_value = mock_runner

        with pytest.raises(click.ClickException, match="Last test run has failures"):
            _run_promote_gate(clean_repo, {})


def test_gate_passes_when_clean_state(clean_repo):
    """With no last-run.json and validate passing, gate does not raise."""
    fake_result = MagicMock()
    fake_result.exit_code = 0
    fake_result.output = "OK"

    with patch("pdm_cli.commands.promote.CliRunner") as mock_runner_cls:
        mock_runner = MagicMock()
        mock_runner.invoke.return_value = fake_result
        mock_runner_cls.return_value = mock_runner

        # Should not raise
        _run_promote_gate(clean_repo, {})


def test_skip_gate_bypasses_gate(tmp_path):
    """--skip-gate flag means _run_promote_gate is never called."""
    from unittest.mock import patch as _patch
    from pdm_cli.commands.promote import promote

    (tmp_path / "pdm.config.yaml").write_text(
        "endpoints:\n  prod: http://prod.local\n", encoding="utf-8"
    )
    (tmp_path / ".pdm").mkdir()
    (tmp_path / ".pdm" / "secrets.yaml").write_text(
        "api_key_prod: key\n", encoding="utf-8"
    )

    with _patch("pdm_cli.commands.promote._git_tag_exists", return_value=True), \
         _patch("pdm_cli.commands.promote._git_is_dirty", return_value=False), \
         _patch("pdm_cli.commands.promote._run_promote_gate") as mock_gate, \
         _patch("pdm_cli.commands.promote._tag_worktree") as mock_wt, \
         _patch("pdm_cli.commands.promote.list_process_slugs", return_value=[]):
        mock_wt.return_value.__enter__ = MagicMock(return_value=tmp_path)
        mock_wt.return_value.__exit__ = MagicMock(return_value=False)

        runner = CliRunner()
        result = runner.invoke(promote, ["v1.0.0", "--skip-gate"],
                               obj={"cwd": str(tmp_path)})

    mock_gate.assert_not_called()
