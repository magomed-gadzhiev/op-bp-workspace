"""Tests for pdm feedback prune CLI command (Etap 9 C3)."""

from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from click.testing import CliRunner

from pdm_cli.commands.feedback import feedback


def test_prune_dry_run(tmp_path):
    """--dry-run shows branches without deleting."""
    runner = CliRunner()

    # Даты считаем от текущего дня: порог удаления по умолчанию — 90 дней
    # (--older-than), фиксированные даты протухают с ходом календаря.
    old_date = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
    recent_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Mock subprocess.run to simulate git branch listing
    old_branch_line = f"feedback/auto-{old_date} {old_date}T10:00:00+03:00"
    recent_branch_line = f"feedback/auto-{recent_date} {recent_date}T10:00:00+03:00"

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        if "branch" in cmd and "--list" in cmd:
            result.returncode = 0
            result.stdout = f"{old_branch_line}\n{recent_branch_line}\n"
        else:
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
        return result

    with patch("pdm_cli.commands.feedback.subprocess.run", side_effect=mock_run):
        with patch("pdm_cli.commands.feedback.os.path.isdir", return_value=True):
            result = runner.invoke(feedback, ["prune", "--dry-run", "--repo-path", str(tmp_path)])

    assert result.exit_code == 0
    assert f"[dry-run] would delete: feedback/auto-{old_date}" in result.output
    assert f"feedback/auto-{recent_date}" not in result.output.replace("Total:", "")


def test_prune_no_branches(tmp_path):
    """No matching branches prints message."""
    runner = CliRunner()

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        return result

    with patch("pdm_cli.commands.feedback.subprocess.run", side_effect=mock_run):
        with patch("pdm_cli.commands.feedback.os.path.isdir", return_value=True):
            result = runner.invoke(feedback, ["prune", "--repo-path", str(tmp_path)])

    assert result.exit_code == 0
    assert "No matching branches found" in result.output
