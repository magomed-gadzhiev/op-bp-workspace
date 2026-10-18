"""Unit tests for db_assert helper (psycopg.connect mocked via monkeypatch)."""

import pytest

from pdm_cli.test_case import DbSideEffect
from pdm_cli.test_runner.db_assert import _build_query, assert_db_side_effect


# ---------- _build_query --------------------------------------------------


def test_build_query_no_where():
    sql, params = _build_query("process_instances", {})
    assert sql == "SELECT count(*) FROM process_instances"
    assert params == []


def test_build_query_single_where():
    sql, params = _build_query("process_instances", {"status": "completed"})
    assert sql == "SELECT count(*) FROM process_instances WHERE status = %s"
    assert params == ["completed"]


def test_build_query_multi_where_sorted():
    # cols sorted for deterministic SQL
    sql, params = _build_query(
        "assignments", {"user_id": 7, "process_instance_id": 42}
    )
    assert sql == (
        "SELECT count(*) FROM assignments "
        "WHERE process_instance_id = %s AND user_id = %s"
    )
    assert params == [42, 7]


# ---------- assert_db_side_effect ----------------------------------------


class _FakeCursor:
    last_sql: str | None = None
    last_params: list | None = None

    def __init__(self, fetchone_result):
        self._fetchone_result = fetchone_result

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        type(self).last_sql = sql
        type(self).last_params = params

    def fetchone(self):
        return self._fetchone_result


class _FakeConn:
    last_dsn: str | None = None

    def __init__(self, dsn, fetchone_result):
        type(self).last_dsn = dsn
        self._fetchone_result = fetchone_result

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _FakeCursor(self._fetchone_result)


def _patch_psycopg(monkeypatch, fetchone_result):
    """Replace psycopg.connect to return a FakeConn yielding fetchone_result."""
    import psycopg

    monkeypatch.setattr(
        psycopg, "connect", lambda dsn: _FakeConn(dsn, fetchone_result)
    )


def test_db_assert_count_above_min(monkeypatch):
    _patch_psycopg(monkeypatch, (3,))
    eff = DbSideEffect(
        kind="db",
        table="process_instances",
        where={"status": "completed"},
        min_count=1,
    )
    matches = assert_db_side_effect("postgresql://stub", eff)
    assert matches == 3
    assert _FakeConn.last_dsn == "postgresql://stub"
    assert _FakeCursor.last_sql == (
        "SELECT count(*) FROM process_instances WHERE status = %s"
    )
    assert _FakeCursor.last_params == ["completed"]


def test_db_assert_exists_true_returns_one(monkeypatch):
    _patch_psycopg(monkeypatch, (1,))
    eff = DbSideEffect(
        kind="db",
        table="entity_state",
        where={"process_instance_id": 99},
        exists=True,
    )
    matches = assert_db_side_effect("postgresql://stub", eff)
    assert matches == 1


def test_db_assert_zero_count(monkeypatch):
    _patch_psycopg(monkeypatch, (0,))
    eff = DbSideEffect(
        kind="db",
        table="assignments",
        where={"user_id": 42},
        min_count=0,
    )
    matches = assert_db_side_effect("postgresql://stub", eff)
    assert matches == 0


def test_db_assert_empty_where(monkeypatch):
    _patch_psycopg(monkeypatch, (17,))
    eff = DbSideEffect(
        kind="db",
        table="process_instances",
        where={},
        min_count=1,
    )
    matches = assert_db_side_effect("postgresql://stub", eff)
    assert matches == 17
    assert _FakeCursor.last_sql == "SELECT count(*) FROM process_instances"
    assert _FakeCursor.last_params == []


def test_db_assert_fetchone_none_returns_zero(monkeypatch):
    # Defensive: empty result set (shouldn't happen for count(*), but be robust)
    _patch_psycopg(monkeypatch, None)
    eff = DbSideEffect(
        kind="db",
        table="process_instances",
        where={"status": "error"},
    )
    matches = assert_db_side_effect("postgresql://stub", eff)
    assert matches == 0


def test_db_assert_whitelist_enforced_upstream():
    # db_assert does NOT re-check the whitelist; the model_validator does.
    with pytest.raises(ValueError, match="not in whitelist"):
        DbSideEffect(kind="db", table="users", where={"id": 1})
