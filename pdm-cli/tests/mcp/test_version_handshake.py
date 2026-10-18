"""On startup, MCP server checks pdm_api_version and exits if incompatible."""

from unittest.mock import MagicMock

import pytest

from pdm_cli.mcp.server import verify_api_version, ApiVersionMismatch


def test_version_match_returns_silently():
    api = MagicMock()
    api.health.return_value = {"pdm_api_version": "1"}
    verify_api_version(api, expected_major="1")  # no raise


def test_version_mismatch_raises():
    api = MagicMock()
    api.health.return_value = {"pdm_api_version": "2"}
    with pytest.raises(ApiVersionMismatch):
        verify_api_version(api, expected_major="1")


def test_missing_field_raises():
    api = MagicMock()
    api.health.return_value = {}
    with pytest.raises(ApiVersionMismatch):
        verify_api_version(api, expected_major="1")


def test_version_with_dot_compares_major_only():
    api = MagicMock()
    api.health.return_value = {"pdm_api_version": "1.4.2"}
    verify_api_version(api, expected_major="1")  # major matches
    api.health.return_value = {"pdm_api_version": "2.0.0"}
    with pytest.raises(ApiVersionMismatch):
        verify_api_version(api, expected_major="1")
