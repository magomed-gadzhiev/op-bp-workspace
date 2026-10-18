"""Tests for get_replay_chain MCP tool (Etap 9 C2)."""

from unittest.mock import MagicMock

import pytest

from pdm_cli.mcp.tools.telemetry import do_get_replay_chain


@pytest.fixture
def mock_api():
    return MagicMock()


def test_replay_chain_happy_path(mock_api):
    """Tool returns chain data from API."""
    mock_api.replay_chain.return_value = {
        "root_run_id": 1,
        "chain": [
            {"run_id": 1, "status": "completed", "started_at": "2026-05-15T10:00:00", "source_run_id": None, "depth": 0},
            {"run_id": 2, "status": "error", "started_at": "2026-05-15T11:00:00", "source_run_id": 1, "depth": 1},
        ],
    }
    result = do_get_replay_chain(mock_api, run_id=2)
    assert result["root_run_id"] == 1
    assert len(result["chain"]) == 2
    mock_api.replay_chain.assert_called_once_with(2)


def test_replay_chain_empty(mock_api):
    """Single run with no replays."""
    mock_api.replay_chain.return_value = {
        "root_run_id": 42,
        "chain": [
            {"run_id": 42, "status": "completed", "started_at": "2026-05-15T10:00:00", "source_run_id": None, "depth": 0},
        ],
    }
    result = do_get_replay_chain(mock_api, run_id=42)
    assert result["root_run_id"] == 42
    assert len(result["chain"]) == 1


def test_replay_chain_api_error(mock_api):
    """API error propagates as exception."""
    import httpx
    mock_api.replay_chain.side_effect = httpx.HTTPStatusError(
        "Not Found", request=MagicMock(), response=MagicMock(status_code=404)
    )
    with pytest.raises(httpx.HTTPStatusError):
        do_get_replay_chain(mock_api, run_id=999)
