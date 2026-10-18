"""Compose entity-clone, HTTP fixture injection, SSH fixture injection and
TestCase run for a `sandbox.replay_with_override` call. Mutex-serialized."""
from __future__ import annotations

import time

from .hoverfly_override import HoverflyOverrideContext, _to_hoverfly_pair
from .ssh_override import SshOverrideContext

# Import test_runner pieces lazily to avoid surprising import-time side effects
MAX_FIXTURES_PER_KIND = 50


def replay_with_override(ctx: dict, run_id: str, overrides: dict | None) -> dict:
    overrides = overrides or {}
    entity_fields = overrides.get("entity_fields") or {}
    http_fixtures = overrides.get("http_fixtures") or []
    ssh_fixtures = overrides.get("ssh_fixtures") or []

    if len(http_fixtures) > MAX_FIXTURES_PER_KIND \
            or len(ssh_fixtures) > MAX_FIXTURES_PER_KIND:
        return _error(run_id,
                      f"too many overrides (max {MAX_FIXTURES_PER_KIND} per kind)")

    start = time.time()
    api = ctx["api"]
    try:
        # Lazy imports avoid pulling test_runner at module-import time
        from ..test_case import TestCase, Expect
        from ..test_runner.runner import RunnerContext, run_case

        with ctx.get("mutex") or _NullCtx():
            # 1. Fetch source run + entity
            src = api.run_details(run_id, include_script_output=False)
            src_entity = (src.get("entity") or {})
            src_entity_id = src_entity.get("id")
            bp_slug = src.get("bp") or src.get("business_process_slug")
            if not (src_entity_id and bp_slug):
                return _error(run_id, "source run missing entity or bp slug")

            # 2. Clone entity with overrides
            new_entity = api.entity_clone_with_overrides(
                src_entity_id, entity_fields)
            new_entity_id = new_entity["id"]

            # 3. Build synthetic TestCase (no side-effect assertions)
            tc = TestCase(
                name=f"replay-{run_id}",
                entity_id=new_entity_id,
                entity=None,
                additional_entities={},
                timeout_sec=min(int(ctx.get("call_timeout", 300)), 600),
                expect=Expect(final_status="completed", side_effects=[]),
            )

            # 4. Inject overrides via two layered context managers
            http_pairs = [_to_hoverfly_pair(o["matcher"], o["response"])
                          for o in http_fixtures]
            with HoverflyOverrideContext(ctx["hoverfly_admin"]) as hf_ctx, \
                 SshOverrideContext(ctx["ssh_override_dir"], run_id) as ssh_ctx:
                if http_pairs:
                    hf_ctx.inject(http_pairs)
                if ssh_fixtures:
                    ssh_ctx.inject([
                        {"request": f["matcher"], "response": f["response"]}
                        for f in ssh_fixtures
                    ])
                # 5. Run via shared runner
                runner_ctx = RunnerContext(
                    hoverfly_admin=ctx["hoverfly_admin"],
                    ssh_replay_journal=ctx["ssh_replay_journal"],
                    sandbox_db_dsn=ctx["sandbox_db_dsn"],
                    pdm_api_base=ctx["pdm_api_base"],
                    pdm_api_key=ctx["pdm_api_key"],
                )
                result = run_case(tc, bp_slug, runner_ctx)

        return {
            "run_id": result.run_id,
            "source_run_id": str(run_id),
            "status": result.status,
            "process_status": result.process_status,
            "assertions": [],
            "duration_sec": round(time.time() - start, 2),
            "error": result.error or "",
            "overrides_applied": {
                "entity_fields_count": len(entity_fields),
                "http_fixtures_count": len(http_fixtures),
                "ssh_fixtures_count": len(ssh_fixtures),
            },
        }
    except Exception as e:
        return _error(run_id, f"{type(e).__name__}: {e}")


def _error(source_run_id: str, msg: str) -> dict:
    return {
        "run_id": None,
        "source_run_id": str(source_run_id),
        "status": "error",
        "process_status": None,
        "assertions": [],
        "duration_sec": 0,
        "error": msg,
        "overrides_applied": {
            "entity_fields_count": 0,
            "http_fixtures_count": 0,
            "ssh_fixtures_count": 0,
        },
    }


class _NullCtx:
    def __enter__(self): return self
    def __exit__(self, *a): return False
