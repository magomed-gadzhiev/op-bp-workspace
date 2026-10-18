"""End-to-end: pdm test produces correlated EgressHttpLog and EgressSshLog entries.

Marked @pytest.mark.e2e — skipped by default. Run via:
  PDM_E2E=1 pytest tests/e2e/test_correlation_e2e.py -v -m e2e

Requires sandbox stack up:
  docker compose -f docker-compose.full.yml -f tools/pdm-cli/sandbox/docker-compose.sandbox.yml up -d
"""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_egress_correlation_end_to_end():
    if not os.environ.get("PDM_E2E"):
        pytest.skip("set PDM_E2E=1 to run")

    # `psycopg` is optional; only imported when test runs
    try:
        import psycopg
    except ImportError:
        pytest.skip("psycopg not installed (pip install psycopg[binary])")

    dsn = os.environ.get(
        "PDM_SANDBOX_DSN",
        "postgresql://pdm:sandbox@localhost:5432/pdm_sandbox_db",
    )
    repo = Path(os.environ.get("PDM_E2E_REPO", "."))

    # 1. Reset egress logs in sandbox DB
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM processes_egresshttplog WHERE 1=1;")
        cur.execute("DELETE FROM processes_egresssshlog WHERE 1=1;")
        conn.commit()

    # 2. Run a known BP test case with HTTP+SSH calls
    subprocess.run(
        ["pdm", "test", "--bp", "sample-bp", "--case", "happy-path", "--keep"],
        cwd=str(repo), check=True, capture_output=True, text=True,
    )
    last = json.loads((repo / ".pdm" / "last-run.json").read_text())
    run_id = int(last["cases"][0]["run_id"])

    # 3. Allow async sidecar to drain
    time.sleep(2)

    # 4. Assert at least one HTTP and one SSH log row exists, both with the run_id
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM processes_egresshttplog WHERE bp_run_id=%s;",
            (run_id,),
        )
        http_count = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM processes_egresssshlog WHERE bp_run_id=%s;",
            (run_id,),
        )
        ssh_count = cur.fetchone()[0]

    assert http_count >= 1, "expected HTTP egress with bp_run_id correlation"
    assert ssh_count >= 1, "expected SSH egress with bp_run_id correlation"
