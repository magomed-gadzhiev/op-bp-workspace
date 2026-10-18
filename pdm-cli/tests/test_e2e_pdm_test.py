"""End-to-end smoke for `pdm test` (Etap 4).

Skipped by default unless PDM_E2E_ETAP4=1 is set in the environment.

Requires the full sandbox stack to be running:

    docker compose -f docker-compose.full.yml \
        -f tools/pdm-cli/sandbox/docker-compose.sandbox.yml up -d

These tests exercise the full `pdm test --ephemeral --keep` pipeline:
real sandbox containers (PDM backend + Hoverfly + ssh-replay), a real BP
pushed to the sandbox, a real HTTP fixture, and the test-case runner
producing a real `.pdm/last-run.json` artifact.

The two scenarios mirror the etap-4 acceptance criteria:

* `test_e2e_happy_case` — fixture covers the BP's HTTP egress; assertions
  pass; runner exits 0; `last-run.json` shows `passed`.
* `test_e2e_red_case_http_no_match` — fixture intentionally does NOT
  cover the egress; Hoverfly answers 502; assertion fails; runner exits 1
  and `last-run.json` shows `failed`.

The bodies are left as manual-validation stubs (see
`docs/superpowers/research/etap-4-discovery.md`). They will be wired in
and run by hand before closing Etap 4. The file MUST stay collectable
under `pytest --collect-only` regardless.
"""
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from pdm_cli.cli import main


pytestmark = pytest.mark.skipif(
    os.environ.get("PDM_E2E_ETAP4") != "1",
    reason="set PDM_E2E_ETAP4=1 to run full sandbox e2e",
)


SANDBOX_PDM_URL = os.environ.get("PDM_E2E_SANDBOX_URL", "http://pdm-backend-sandbox:8000")
SANDBOX_API_KEY = os.environ.get("PDM_E2E_SANDBOX_API_KEY", "")
HOVERFLY_URL = os.environ.get("HOVERFLY_URL", "http://hoverfly:8888")


def _bootstrap_repo(tmp_path: Path) -> Path:
    """Materialise a minimal pdm-cli workspace pointing at the sandbox stack."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "bootstrap",
            "--pdm-url", SANDBOX_PDM_URL, "--api-key", SANDBOX_API_KEY,
            "--sandbox-url", SANDBOX_PDM_URL, "--api-key-sandbox", SANDBOX_API_KEY,
        ],
        obj={"cwd": tmp_path},
    )
    assert result.exit_code == 0, result.output
    return tmp_path


def test_e2e_happy_case(tmp_path: Path):
    """End-to-end: real sandbox, real BP, real HTTP fixture, assertion passes.

    Expected flow (manual validation):
      1. Bootstrap workspace pointing at sandbox stack.
      2. Author a minimal BP `demo-bp` with one HTTP-calling script.
      3. Capture/record an HTTP fixture that covers the call.
      4. Author a case asserting `kind:http` count >= 1.
      5. Run `pdm test --bp demo-bp --case happy --ephemeral --keep`.
      6. Assert exit_code == 0 and `.pdm/last-run.json` shows `passed`.
    """
    pytest.skip(
        "manual validation needed; see docs/superpowers/research/etap-4-discovery.md "
        "(requires fully seeded sandbox with BP + fixture)."
    )
    # Skeleton kept for when this is wired up manually:
    # root = _bootstrap_repo(tmp_path)
    # runner = CliRunner()
    # result = runner.invoke(
    #     main,
    #     ["test", "--bp", "demo-bp", "--case", "happy", "--ephemeral", "--keep"],
    #     obj={"cwd": root},
    # )
    # assert result.exit_code == 0, result.output
    # last_run = (root / ".pdm" / "last-run.json").read_text(encoding="utf-8")
    # assert '"status": "passed"' in last_run


def test_e2e_red_case_http_no_match(tmp_path: Path):
    """Sandbox returns 502, runner marks case failed (exit 1).

    Expected flow (manual validation):
      1. Bootstrap workspace.
      2. Push BP that performs an HTTP call NOT covered by any fixture.
      3. Run `pdm test --bp demo-bp --case red --ephemeral --keep`.
      4. Hoverfly responds 502 (no matching simulation).
      5. Assert exit_code == 1 and `.pdm/last-run.json` shows `failed`
         with the HTTP-egress assertion failure surfaced.
    """
    pytest.skip(
        "manual validation needed; see docs/superpowers/research/etap-4-discovery.md "
        "(requires fully seeded sandbox without matching fixture)."
    )
    # Skeleton kept for when this is wired up manually:
    # root = _bootstrap_repo(tmp_path)
    # runner = CliRunner()
    # result = runner.invoke(
    #     main,
    #     ["test", "--bp", "demo-bp", "--case", "red", "--ephemeral", "--keep"],
    #     obj={"cwd": root},
    # )
    # assert result.exit_code == 1, result.output
    # last_run = (root / ".pdm" / "last-run.json").read_text(encoding="utf-8")
    # assert '"status": "failed"' in last_run
