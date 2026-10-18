import importlib.util
import os
import sys
import pathlib

import pytest

from tests.baseline_guard import evaluate_baseline

_BP = pathlib.Path(__file__).resolve().parents[1] / "sandbox" / "ssh-bastion" / "bastion.py"
_spec = importlib.util.spec_from_file_location("tools_pdm_sandbox_ssh_bastion_compat", _BP)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["tools_pdm_sandbox_ssh_bastion_compat"] = _mod
_spec.loader.exec_module(_mod)

# --- E17 test-baseline drift guard (specs/037, docs/TESTING.md) ----------------
# Default expected skip count for the full pdm-cli suite. Override the explicit
# baseline with PDM_SKIP_BASELINE; opt into the count check with PDM_BASELINE_CHECK.
_BASELINE_SKIPS = 13
_skipped: dict[str, str] = {}


def _skip_reason(report) -> str:
    lr = report.longrepr
    reason = ""
    if isinstance(lr, tuple) and len(lr) == 3:
        reason = lr[2] or ""
    elif isinstance(lr, str):
        reason = lr
    if reason.startswith("Skipped: "):
        reason = reason[len("Skipped: ") :]
    reason = reason.strip()
    # pytest's placeholder for a bare ``@pytest.mark.skip`` (no explanation).
    if reason == "unconditional skip":
        return ""
    return reason


def pytest_runtest_logreport(report):
    # Count a test as skipped once; exclude xfail (reported skipped at call).
    if report.skipped and not getattr(report, "wasxfail", False):
        _skipped.setdefault(report.nodeid, _skip_reason(report))


def pytest_sessionfinish(session, exitstatus):
    baseline = int(os.environ.get("PDM_SKIP_BASELINE", _BASELINE_SKIPS))
    check_count = bool(os.environ.get("PDM_BASELINE_CHECK"))
    reasonless = sorted(nid for nid, reason in _skipped.items() if not reason)
    violations = evaluate_baseline(
        len(_skipped), baseline, reasonless, check_count=check_count
    )
    if violations:
        tr = session.config.pluginmanager.get_plugin("terminalreporter")
        if tr is not None:
            tr.write_line("")
            tr.write_line("E17 baseline guard: violations detected", red=True)
            for v in violations:
                tr.write_line(f"  {v}", red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
