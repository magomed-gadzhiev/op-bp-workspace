"""sandbox.run_test / sandbox.run_step / sandbox.replay_with_override."""
from __future__ import annotations

import time
from pathlib import Path

from ...api_client import SandboxLockConflict
from ...test_runner.runner import RunnerContext, run_case
from ..replay_orchestrator import replay_with_override as _replay_with_override
from ..server import _lock_conflict_result


_MAX_CALL_TIMEOUT = 600


def _load_test_case(repo_root: Path, bp: str, case: str):
    """Load `processes/<bp>/tests/<case>.yaml` and return parsed TestCase."""
    path = Path(repo_root) / "processes" / bp / "tests" / f"{case}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"test case not found: {path}")
    from ...test_case import load_test_case
    return load_test_case(path)


def _build_runner_ctx(ctx: dict) -> RunnerContext:
    return RunnerContext(
        hoverfly_admin=ctx["hoverfly_admin"],
        ssh_replay_journal=ctx["ssh_replay_journal"],
        sandbox_db_dsn=ctx["sandbox_db_dsn"],
        pdm_api_base=ctx["pdm_api_base"],
        pdm_api_key=ctx["pdm_api_key"],
        cli_bypass_secret="",
    )


def _impl_run_test(ctx: dict, bp: str, case: str) -> dict:
    start = time.time()
    try:
        tc = _load_test_case(ctx["repo_root"], bp, case)
        # Pydantic model — assignment is OK on instance (BaseModel allows
        # attribute mutation unless model_config sets frozen=True).
        try:
            tc.timeout_sec = min(
                int(getattr(tc, "timeout_sec", 60)),
                int(ctx.get("call_timeout", 300)),
                _MAX_CALL_TIMEOUT,
            )
        except Exception:
            # If frozen — fall back to model_copy with update
            tc = tc.model_copy(update={
                "timeout_sec": min(
                    int(getattr(tc, "timeout_sec", 60)),
                    int(ctx.get("call_timeout", 300)),
                    _MAX_CALL_TIMEOUT,
                )
            })
        with ctx["mutex"]:
            r = run_case(tc, bp, _build_runner_ctx(ctx))
        return {
            "run_id": r.run_id,
            "status": r.status,
            "process_status": r.process_status,
            "assertions": [
                {"index": a.index, "kind": a.kind, "status": a.status,
                 "expected": a.expected, "got": a.got, "explain": a.explain}
                for a in r.assertions
            ],
            "duration_sec": round(time.time() - start, 2),
            "error": r.error or "",
        }
    except Exception as e:
        return {
            "run_id": None,
            "status": "error",
            "process_status": None,
            "assertions": [],
            "duration_sec": round(time.time() - start, 2),
            "error": f"{type(e).__name__}: {e}",
        }


def _impl_run_step(ctx: dict, run_id: str, step_id: str,
                   input_overrides: dict | None) -> dict:
    """sandbox.run_step — no mutex (dry-run doesn't touch shared state)."""
    try:
        body = ctx["api"].replay_step(
            run_id,
            step_id,
            input_overrides or {},
            override_owner=ctx.get("override_owner"),
        )
        return body
    except SandboxLockConflict as e:
        return _lock_conflict_result(e.body)
    except Exception as e:
        return {
            "executed": False,
            "stdout": "", "stderr": "",
            "execution_time_sec": 0,
            "result": {},
            "context_data_diff": {"before": {}, "after": {}},
            "egress_during_step": {"http": [], "ssh": []},
            "error": f"{type(e).__name__}: {e}",
        }


def register(server, ctx):
    @server.tool(name="sandbox.run_test",
                 description="Run a single test case from processes/<bp>/tests/<case>.yaml "
                             "against the sandbox stack. Blocks until completion.")
    def run_test(bp: str, case: str) -> dict:
        return _impl_run_test(ctx, bp, case)

    @server.tool(name="sandbox.run_step",
                 description="Replay one step of an existing run in dry-run "
                             "mode — no DB mutation, returns context_data_diff.")
    def run_step(run_id: str, step_id: str,
                 input_overrides: dict | None = None) -> dict:
        return _impl_run_step(ctx, run_id, step_id, input_overrides)

    @server.tool(name="sandbox.replay_with_override",
                 description="Re-run a sandbox run with entity_fields / "
                             "http_fixtures / ssh_fixtures overrides. Creates a new run_id.")
    def replay_with_override(run_id: str, overrides: dict | None = None) -> dict:
        return _replay_with_override(ctx, run_id, overrides)
