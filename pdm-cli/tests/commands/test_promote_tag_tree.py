"""Tests for promote tag-tree: tag-not-found exit 1, worktree lifecycle, dirty-tree warning."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
from click.testing import CliRunner

from pdm_cli.commands.promote import promote


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "pdm.config.yaml").write_text(
        "endpoints:\n  prod: http://prod.local\n", encoding="utf-8"
    )
    (tmp_path / ".pdm").mkdir()
    (tmp_path / ".pdm" / "secrets.yaml").write_text(
        "api_key_prod: key\n", encoding="utf-8"
    )
    return tmp_path


def test_tag_not_found_exits_1(repo):
    """If the git tag does not exist, promote exits with code 1."""
    with patch("pdm_cli.commands.promote._git_tag_exists", return_value=False):
        runner = CliRunner()
        result = runner.invoke(promote, ["v0.0.0"], obj={"cwd": str(repo)})
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_tag_exists_worktree_created_and_cleaned(repo):
    """When tag exists, _tag_worktree is entered and exited (cleanup guaranteed)."""
    mock_slugs = ["my-process"]

    with patch("pdm_cli.commands.promote._git_tag_exists", return_value=True), \
         patch("pdm_cli.commands.promote._git_is_dirty", return_value=False), \
         patch("pdm_cli.commands.promote._run_promote_gate"), \
         patch("pdm_cli.commands.promote._tag_worktree") as mock_wt_ctx, \
         patch("pdm_cli.commands.promote.list_process_slugs", return_value=mock_slugs), \
         patch("pdm_cli.commands.promote.read_process") as mock_read, \
         patch("pdm_cli.commands.promote.PdmApiClient") as mock_client_cls:

        mock_wt_ctx.return_value.__enter__ = MagicMock(return_value=repo)
        mock_wt_ctx.return_value.__exit__ = MagicMock(return_value=False)

        mock_imported = MagicMock()
        mock_imported.manifest.version = "1"
        mock_published = MagicMock()
        mock_published.manifest.version = "2"

        mock_client = MagicMock()
        mock_client.import_full.return_value = mock_imported
        mock_client.promote.return_value = mock_published
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        runner = CliRunner()
        result = runner.invoke(promote, ["v1.0.0"], obj={"cwd": str(repo)})

    mock_wt_ctx.assert_called_once()
    mock_wt_ctx.return_value.__enter__.assert_called_once()
    mock_wt_ctx.return_value.__exit__.assert_called_once()
    assert result.exit_code == 0


def test_dirty_working_tree_warns_not_blocks(repo):
    """Uncommitted changes in working tree produce a warning but do not abort."""
    with patch("pdm_cli.commands.promote._git_tag_exists", return_value=True), \
         patch("pdm_cli.commands.promote._git_is_dirty", return_value=True), \
         patch("pdm_cli.commands.promote._run_promote_gate"), \
         patch("pdm_cli.commands.promote._tag_worktree") as mock_wt_ctx, \
         patch("pdm_cli.commands.promote.list_process_slugs", return_value=[]):

        mock_wt_ctx.return_value.__enter__ = MagicMock(return_value=repo)
        mock_wt_ctx.return_value.__exit__ = MagicMock(return_value=False)

        runner = CliRunner()
        result = runner.invoke(promote, ["v1.0.0"], obj={"cwd": str(repo)})

    assert result.exit_code == 0
    assert "uncommitted changes" in result.output
