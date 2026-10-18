"""Tests for pdm decks push/drift: чтение YAML, вызов API, exit-коды."""

from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from pdm_cli.cli import main

DECK = {
    "name": "ui150-demo-drc",
    "kind": "drc",
    "version": 1,
    "rules": [
        {"rule_name": "L41_min_width", "layer": 41, "datatype": 0,
         "min_value_nm": 180, "description": "width >= 180nm on L41"},
    ],
}


@pytest.fixture
def repo(tmp_path):
    decks_dir = tmp_path / "processes" / "150" / "decks"
    decks_dir.mkdir(parents=True)
    (decks_dir / "ui150-demo-drc.yaml").write_text(
        yaml.safe_dump(DECK, allow_unicode=True), encoding="utf-8")
    return tmp_path


def _invoke(repo, *args, **kwargs):
    runner = CliRunner()
    return runner.invoke(main, ["decks", *args], obj={"cwd": repo}, **kwargs)


def test_push_reads_yaml_and_posts(repo):
    client = MagicMock()
    client.decks_import.return_value = {
        "imported": [{"name": "ui150-demo-drc", "version": 1}],
        "unchanged": [], "conflicts": [], "preview": False,
    }
    with patch("pdm_cli.commands.decks.make_client") as mc:
        mc.return_value.__enter__.return_value = client
        result = _invoke(repo, "push")
    assert result.exit_code == 0, result.output
    client.decks_import.assert_called_once()
    payload = client.decks_import.call_args[0][0]
    assert payload[0]["name"] == "ui150-demo-drc"
    assert client.decks_import.call_args[1] == {"confirm": True}
    assert "материализован" in result.output


def test_push_dry_run_previews(repo):
    client = MagicMock()
    client.decks_import.return_value = {
        "imported": [{"name": "ui150-demo-drc", "version": 1}],
        "unchanged": [], "conflicts": [], "preview": True,
    }
    with patch("pdm_cli.commands.decks.make_client") as mc:
        mc.return_value.__enter__.return_value = client
        result = _invoke(repo, "push", "--dry-run")
    assert result.exit_code == 0
    assert client.decks_import.call_args[1] == {"confirm": False}


def test_push_conflict_exits_nonzero(repo):
    client = MagicMock()
    client.decks_import.return_value = {
        "imported": [], "unchanged": [],
        "conflicts": [{"name": "ui150-demo-drc", "version": 1,
                       "reason": "поднимите version"}],
        "preview": False,
    }
    with patch("pdm_cli.commands.decks.make_client") as mc:
        mc.return_value.__enter__.return_value = client
        result = _invoke(repo, "push")
    assert result.exit_code == 1
    assert "поднимите version" in result.output


def test_drift_in_sync_exits_zero(repo):
    client = MagicMock()
    client.decks_drift.return_value = {
        "in_sync": [{"name": "ui150-demo-drc", "detail": "v1"}],
        "in_drift": False,
    }
    with patch("pdm_cli.commands.decks.make_client") as mc:
        mc.return_value.__enter__.return_value = client
        result = _invoke(repo, "drift")
    assert result.exit_code == 0, result.output
    assert "Дрейфа нет" in result.output


def test_drift_ahead_exits_nonzero(repo):
    client = MagicMock()
    client.decks_drift.return_value = {
        "ahead": [{"name": "ui150-demo-drc", "detail": "git v2, БД v1"}],
        "in_drift": True,
    }
    with patch("pdm_cli.commands.decks.make_client") as mc:
        mc.return_value.__enter__.return_value = client
        result = _invoke(repo, "drift")
    assert result.exit_code == 1
    assert "ahead" in result.output


def test_no_decks_is_silent_ok(tmp_path):
    with patch("pdm_cli.commands.decks.make_client") as mc:
        result = _invoke(tmp_path, "push")
    assert result.exit_code == 0
    mc.assert_not_called()
