"""Tests for pdm_cli.fixtures.loader: http/ssh dispatch, unknown prefix, unload."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from ruamel.yaml import YAML

from pdm_cli.fixtures.loader import (
    load_fixtures_for_case,
    unload_fixtures_for_case,
)


def _write_http_fixture(path: Path, name: str = "my-fixture") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    y = YAML()
    y.default_flow_style = False
    with path.open("w", encoding="utf-8") as f:
        y.dump(
            {
                "name": name,
                "matchers": [
                    {
                        "request": {
                            "method": "GET",
                            "url_matches": "http://example.com/api",
                            "headers": {},
                            "body_contains": [],
                        },
                        "response": {"status": 200, "headers": {}, "body": "ok", "delay_ms": 0},
                    }
                ],
            },
            f,
        )


def _write_ssh_fixture(path: Path, name: str = "ssh-fix") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    y = YAML()
    y.default_flow_style = False
    with path.open("w", encoding="utf-8") as f:
        y.dump(
            {
                "name": name,
                "matchers": [
                    {
                        "request": {
                            "host": "host1",
                            "user": "deploy",
                            "command_matches": "^echo",
                        },
                        "response": {"stdout": "hello", "stderr": "", "exit_code": 0, "duration_ms": 0},
                    }
                ],
            },
            f,
        )


@pytest.fixture
def bp_dir(tmp_path):
    return tmp_path / "processes" / "my-bp"


@pytest.fixture
def ctx(tmp_path):
    return MagicMock(
        hoverfly_admin="http://localhost:8888",
        ssh_override_dir=str(tmp_path / "ssh-overrides"),
    )


@pytest.fixture
def tc():
    return MagicMock(fixtures=[])


def test_http_fixture_loads_via_hoverfly(bp_dir, ctx, tc):
    """http-* fixture calls HoverflyClient.put_simulation."""
    fixture_path = bp_dir / "fixtures" / "http-my-req.yaml"
    _write_http_fixture(fixture_path)
    tc.fixtures = ["http-my-req"]

    with patch("pdm_cli.fixtures.loader.HoverflyClient") as mock_hf_cls:
        mock_hf = MagicMock()
        mock_hf_cls.return_value = mock_hf
        loaded = load_fixtures_for_case(tc, bp_dir, ctx)

    mock_hf.put_simulation.assert_called_once()
    assert loaded == ["http-my-req"]


def test_ssh_fixture_writes_override_file(bp_dir, ctx, tc, tmp_path):
    """ssh-* fixture writes a YAML file to ssh_override_dir."""
    fixture_path = bp_dir / "fixtures" / "ssh-deploy.yaml"
    _write_ssh_fixture(fixture_path)
    tc.fixtures = ["ssh-deploy"]

    loaded = load_fixtures_for_case(tc, bp_dir, ctx)

    override_file = Path(ctx.ssh_override_dir) / "fixture-ssh-deploy.yaml"
    assert override_file.is_file()
    assert loaded == ["ssh-deploy"]


def test_unknown_prefix_raises_runtime_error(bp_dir, ctx, tc):
    """Fixture name with unknown prefix raises RuntimeError."""
    fixture_path = bp_dir / "fixtures" / "ftp-bad.yaml"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text("name: ftp-bad\nmatchers: []\n", encoding="utf-8")
    tc.fixtures = ["ftp-bad"]

    with pytest.raises(RuntimeError, match="Unknown fixture prefix"):
        load_fixtures_for_case(tc, bp_dir, ctx)


def test_unload_fixtures_calls_hoverfly_delete(ctx):
    """unload_fixtures_for_case calls HoverflyClient.delete_simulation for http fixtures."""
    with patch("pdm_cli.fixtures.loader.HoverflyClient") as mock_hf_cls:
        mock_hf = MagicMock()
        mock_hf_cls.return_value = mock_hf
        unload_fixtures_for_case(["http-my-req"], ctx)

    mock_hf.delete_simulation.assert_called_once()
