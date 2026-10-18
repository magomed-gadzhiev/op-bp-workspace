"""Etap 7 Phase 4 — sandbox.run_test + sandbox.run_step (impl-level tests)."""
from unittest.mock import patch, MagicMock

from pdm_cli.api_client import SandboxLockConflict
from pdm_cli.sandbox_mcp.tools.run import _impl_run_test, _impl_run_step


class _DummyMutex:
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _stub_ctx():
    return {
        "repo_root": MagicMock(),
        "hoverfly_admin": "http://hf",
        "ssh_replay_journal": "http://ssh-j",
        "sandbox_db_dsn": "",
        "pdm_api_base": "http://api",
        "pdm_api_key": "k",
        "cfg": MagicMock(),
        "mutex": _DummyMutex(),
        "call_timeout": 300,
        "override_owner": "owner-1",
    }


def test_run_test_returns_status_and_assertions():
    fake_result = MagicMock()
    fake_result.run_id = "1234"
    fake_result.status = "passed"
    fake_result.process_status = "completed"
    fake_result.assertions = [
        MagicMock(index=0, kind="http", status="passed",
                  expected=">=1", got=2, explain=""),
    ]
    fake_result.error = ""
    with patch("pdm_cli.sandbox_mcp.tools.run._load_test_case") as load_tc, \
         patch("pdm_cli.sandbox_mcp.tools.run.run_case", return_value=fake_result):
        load_tc.return_value = MagicMock(timeout_sec=60)
        out = _impl_run_test(_stub_ctx(), "payroll", "happy")
    assert out["run_id"] == "1234"
    assert out["status"] == "passed"
    assert out["assertions"][0]["kind"] == "http"
    assert out["assertions"][0]["got"] == 2


def test_run_test_bp_not_found_returns_error():
    with patch("pdm_cli.sandbox_mcp.tools.run._load_test_case",
               side_effect=FileNotFoundError("no such case")):
        out = _impl_run_test(_stub_ctx(), "payroll", "missing")
    assert out["status"] == "error"
    assert "no such case" in out["error"]


def test_run_step_returns_executor_output():
    api = MagicMock()
    api.replay_step.return_value = {
        "executed": True, "stdout": "ok", "stderr": "",
        "execution_time_sec": 0.1, "result": {"v": 2},
        "context_data_diff": {"before": {"v": 1}, "after": {"v": 2}},
        "egress_during_step": {"http": [], "ssh": []},
        "error": None,
    }
    ctx = _stub_ctx()
    ctx["api"] = api
    out = _impl_run_step(ctx, "42", "calc", {"v": 2})
    assert out["executed"] is True
    assert out["result"]["v"] == 2
    api.replay_step.assert_called_once_with(
        "42", "calc", {"v": 2}, override_owner="owner-1")


def test_run_step_handles_lock_conflict():
    api = MagicMock()
    api.replay_step.side_effect = SandboxLockConflict({
        "current_owner": "other-sb",
        "retry_after": 10,
    })
    ctx = _stub_ctx()
    ctx["api"] = api

    out = _impl_run_step(ctx, "42", "calc", None)

    assert out["status"] == "locked"
    assert out["current_owner"] == "other-sb"
    assert "other-sb" in out["message"]


def test_run_step_propagates_api_error():
    api = MagicMock()
    api.replay_step.side_effect = RuntimeError("api down")
    ctx = _stub_ctx()
    ctx["api"] = api
    out = _impl_run_step(ctx, "42", "calc", None)
    assert out["executed"] is False
    assert "api down" in out["error"]
