"""Tests for pdm_cli.test_runner.runner (orchestration of one TestCase).

Strategy: monkeypatch the runner module's helpers + journal clients +
db_assert. This keeps tests focused on orchestration logic (status
transitions, assertion aggregation, timeout/cancel) without dragging in
httpx/respx for every step.
"""
from __future__ import annotations

import pytest

from pdm_cli.test_case import TestCase
from pdm_cli.test_runner import runner as runner_mod
from pdm_cli.test_runner.runner import CaseResult, RunnerContext, run_case


@pytest.fixture
def ctx():
    return RunnerContext(
        hoverfly_admin="http://hoverfly:8888",
        ssh_replay_journal="http://ssh-replay:9090",
        sandbox_db_dsn="postgresql://u:p@db:5432/sandbox",
        pdm_api_base="http://pdm-sandbox:8000",
        pdm_api_key="superuser-token",
    )


def _patch_journals_and_db(monkeypatch, *, http_matches=None,
                            ssh_matches=None, db_count=0):
    """Stub clear_*/match_*/assert_db helpers on the runner module."""
    monkeypatch.setattr(runner_mod, "clear_journal", lambda *_: None)
    monkeypatch.setattr(runner_mod, "clear_ssh_journal", lambda *_: None)
    monkeypatch.setattr(
        runner_mod, "match_http_side_effect",
        lambda *_a, **_kw: list(http_matches or []),
    )
    monkeypatch.setattr(
        runner_mod, "match_ssh_side_effect",
        lambda *_a, **_kw: list(ssh_matches or []),
    )
    monkeypatch.setattr(
        runner_mod, "assert_db_side_effect", lambda *_a, **_kw: db_count,
    )


def _patch_api(monkeypatch, *, run_id="42", final_status="completed",
                poll_sequence=None, create_calls=None,
                resolve_bp=lambda *_: 7,
                resolve_type=lambda *_: 3):
    """Stub the API helpers (no httpx)."""
    monkeypatch.setattr(runner_mod, "_resolve_bp_id", resolve_bp)
    monkeypatch.setattr(runner_mod, "_resolve_entity_type_id", resolve_type)

    if create_calls is not None:
        def _create(ctx, tc):
            create_calls.append(tc)
            return 100
        monkeypatch.setattr(runner_mod, "_create_entity", _create)
    else:
        monkeypatch.setattr(
            runner_mod, "_create_entity",
            lambda *a, **kw: (_ for _ in ()).throw(
                AssertionError("_create_entity must not be called")
            ),
        )

    monkeypatch.setattr(
        runner_mod, "_start_bp", lambda *a, **kw: run_id,
    )

    if poll_sequence is None:
        poll_sequence = [{"status": final_status}]
    poll_iter = iter(poll_sequence)

    def _poll(ctx, rid, deadline):
        try:
            return next(poll_iter)
        except StopIteration:
            return None

    monkeypatch.setattr(runner_mod, "_poll", _poll)

    cancel_calls = []
    monkeypatch.setattr(
        runner_mod, "_cancel",
        lambda ctx, rid: cancel_calls.append(rid),
    )
    return cancel_calls


def test_runner_happy_path(monkeypatch, ctx):
    """All side-effects satisfied → status=passed."""
    _patch_journals_and_db(monkeypatch, http_matches=[{"x": 1}])
    _patch_api(monkeypatch)
    tc = TestCase.model_validate({
        "name": "happy",
        "entity_id": 99,
        "expect": {
            "final_status": "completed",
            "side_effects": [
                {"kind": "http", "url_matches": "/a", "min_count": 1},
            ],
        },
    })
    result = run_case(tc, "demo-bp", ctx)
    assert isinstance(result, CaseResult)
    assert result.status == "passed"
    assert result.process_status == "completed"
    assert result.run_id == "42"
    assert len(result.assertions) == 1
    assert result.assertions[0].status == "passed"
    assert result.assertions[0].kind == "http"
    assert result.assertions[0].got == 1


def test_runner_entity_id_skips_creation(monkeypatch, ctx):
    """When entity_id is set, _create_entity is NOT called."""
    _patch_journals_and_db(monkeypatch)
    # _create_entity will raise AssertionError if invoked.
    _patch_api(monkeypatch)
    tc = TestCase.model_validate({
        "name": "skip-create",
        "entity_id": 555,
        "expect": {"final_status": "completed"},
    })
    result = run_case(tc, "bp", ctx)
    assert result.status == "passed"
    assert result.assertions == []


def test_runner_entity_block_creates_entity(monkeypatch, ctx):
    """entity block → _create_entity is called and its id flows through."""
    _patch_journals_and_db(monkeypatch)
    create_calls: list[TestCase] = []
    _patch_api(monkeypatch, create_calls=create_calls)
    tc = TestCase.model_validate({
        "name": "create",
        "entity": {"type": "Project", "fields": {"name": "x"}},
        "expect": {"final_status": "completed"},
    })
    result = run_case(tc, "bp", ctx)
    assert result.status == "passed"
    assert len(create_calls) == 1
    assert create_calls[0].entity is not None
    assert create_calls[0].entity.type == "Project"


def test_runner_timeout(monkeypatch, ctx):
    """Poll returns None (deadline) → status=timeout, _cancel called."""
    _patch_journals_and_db(monkeypatch)
    # Empty poll_sequence ⇒ _poll returns None immediately (timeout).
    cancel_calls = _patch_api(monkeypatch, poll_sequence=[])
    tc = TestCase.model_validate({
        "name": "timeout",
        "entity_id": 1,
        "timeout_sec": 1,
        "expect": {"final_status": "completed"},
    })
    result = run_case(tc, "bp", ctx)
    assert result.status == "timeout"
    assert result.process_status == "cancelled"
    assert cancel_calls == ["42"]


def test_runner_assertion_failure_min_count(monkeypatch, ctx):
    """HTTP side-effect with 0 matches but min_count=1 → status=failed."""
    _patch_journals_and_db(monkeypatch, http_matches=[])
    _patch_api(monkeypatch)
    tc = TestCase.model_validate({
        "name": "miss",
        "entity_id": 1,
        "expect": {
            "final_status": "completed",
            "side_effects": [
                {"kind": "http", "url_matches": "/a", "min_count": 1},
            ],
        },
    })
    result = run_case(tc, "bp", ctx)
    assert result.status == "failed"
    assert result.assertions[0].status == "failed"
    assert result.assertions[0].got == 0
    assert "expected >= 1" in result.assertions[0].explain


def test_runner_assertion_failure_max_count(monkeypatch, ctx):
    """HTTP side-effect exceeding max_count → status=failed."""
    _patch_journals_and_db(
        monkeypatch, http_matches=[{"x": 1}, {"x": 2}, {"x": 3}],
    )
    _patch_api(monkeypatch)
    tc = TestCase.model_validate({
        "name": "too-many",
        "entity_id": 1,
        "expect": {
            "final_status": "completed",
            "side_effects": [
                {"kind": "http", "url_matches": "/a",
                 "min_count": 1, "max_count": 2},
            ],
        },
    })
    result = run_case(tc, "bp", ctx)
    assert result.status == "failed"
    assert result.assertions[0].status == "failed"
    assert result.assertions[0].got == 3
    assert "expected <= 2" in result.assertions[0].explain


def test_runner_final_status_mismatch(monkeypatch, ctx):
    """Process ends with `error` but expected `completed` → failed; side-effects skipped."""
    _patch_journals_and_db(monkeypatch, http_matches=[{"x": 1}])
    _patch_api(monkeypatch, poll_sequence=[{"status": "error"}])
    tc = TestCase.model_validate({
        "name": "wrong-status",
        "entity_id": 1,
        "expect": {
            "final_status": "completed",
            "side_effects": [
                {"kind": "http", "url_matches": "/a", "min_count": 1},
            ],
        },
    })
    result = run_case(tc, "bp", ctx)
    assert result.status == "failed"
    assert result.process_status == "error"
    # Only the synthetic final_status assertion is recorded; side-effects skipped.
    assert len(result.assertions) == 1
    assert result.assertions[0].kind == "final_status"
    assert result.assertions[0].expected == "completed"
    assert "got error" in result.assertions[0].explain


def test_runner_multiple_side_effects_aggregated(monkeypatch, ctx):
    """http=ok, ssh=ok, db=fail → overall failed; all 3 recorded."""
    _patch_journals_and_db(
        monkeypatch,
        http_matches=[{"x": 1}],
        ssh_matches=[{"command": "ls"}],
        db_count=0,  # fails min_count=1
    )
    _patch_api(monkeypatch)
    tc = TestCase.model_validate({
        "name": "mixed",
        "entity_id": 1,
        "expect": {
            "final_status": "completed",
            "side_effects": [
                {"kind": "http", "url_matches": "/a", "min_count": 1},
                {"kind": "ssh", "command_matches": "ls", "min_count": 1},
                {"kind": "db", "table": "process_instances",
                 "where": {"id": 1}, "min_count": 1},
            ],
        },
    })
    result = run_case(tc, "bp", ctx)
    assert result.status == "failed"
    assert len(result.assertions) == 3
    assert [a.status for a in result.assertions] == ["passed", "passed", "failed"]
    assert [a.kind for a in result.assertions] == ["http", "ssh", "db"]


def test_runner_polls_until_terminal(monkeypatch, ctx):
    """First poll returns running (None from _poll's perspective is timeout;
    we model the loop-until-terminal as poll returning the terminal dict)."""
    _patch_journals_and_db(monkeypatch)
    _patch_api(monkeypatch, poll_sequence=[{"status": "completed"}])
    tc = TestCase.model_validate({
        "name": "ok",
        "entity_id": 1,
        "expect": {"final_status": "completed"},
    })
    result = run_case(tc, "bp", ctx)
    assert result.status == "passed"
    assert result.process_status == "completed"


def test_runner_raises_in_helper_yields_error_status(monkeypatch, ctx):
    """Any exception during orchestration → status=error with error message."""
    _patch_journals_and_db(monkeypatch)
    monkeypatch.setattr(
        runner_mod, "_resolve_bp_id",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    tc = TestCase.model_validate({
        "name": "err",
        "entity_id": 1,
        "expect": {"final_status": "completed"},
    })
    result = run_case(tc, "bp", ctx)
    assert result.status == "error"
    assert "boom" in result.error
