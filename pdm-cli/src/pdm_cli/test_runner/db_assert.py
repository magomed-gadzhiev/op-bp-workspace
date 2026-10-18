"""SQL-based assertions for kind:db side effects against pdm-postgres-sandbox.

The DbSideEffect Pydantic model (pdm_cli.test_case) enforces the table whitelist
in its model_validator — this module trusts that gate and does NOT re-check.
Helper builds a parametrized `SELECT count(*) FROM <table> WHERE <cols>` and
returns the matched row count. The caller decides whether the count satisfies
min_count / max_count / exists / count.
"""

from __future__ import annotations

from typing import Any

import psycopg

from pdm_cli.test_case import DbSideEffect


def _build_query(table: str, where: dict[str, Any]) -> tuple[str, list[Any]]:
    """Construct `SELECT count(*) FROM <table> [WHERE ...]`.

    Column names come from a whitelisted DbSideEffect — we sort them for
    deterministic SQL (useful for assertions in tests) and parametrize values.
    """
    if not where:
        return f"SELECT count(*) FROM {table}", []
    cols = sorted(where.keys())
    clauses = " AND ".join(f"{c} = %s" for c in cols)
    params = [where[c] for c in cols]
    return f"SELECT count(*) FROM {table} WHERE {clauses}", params


def assert_db_side_effect(dsn: str, eff: DbSideEffect) -> int:
    """Run the count(*) query for `eff` and return matched row count.

    Whitelist enforcement is upstream (DbSideEffect validator); the caller is
    responsible for interpreting the count against min_count/max_count/exists.
    """
    sql, params = _build_query(eff.table, eff.where)
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
    if row is None:
        return 0
    (n,) = row
    return int(n)
