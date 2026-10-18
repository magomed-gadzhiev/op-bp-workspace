"""Orchestrates one TestCase against the sandbox stack.

`run_case(tc, bp_slug, ctx)` walks the lifecycle:
  1. Clear Hoverfly / ssh-replay journals.
  2. Resolve BP int id from slug, create entity (or reuse `entity_id`).
  3. POST /api/business-processes/<id>/start_for_entity/, record `run_id`.
  4. Poll /api/process-instances/<run_id>/ until terminal status or timeout.
  5. On timeout — PATCH status=cancelled (best-effort).
  6. Compare `process.status` vs `expect.final_status`, evaluate side-effects.
  7. Return CaseResult with assertions[] + final status.

API shape comes from `docs/etap-4-discovery.md`. Superuser token required
because the runner creates entities and starts BPs (regular users can't).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from ..test_case import (
    DbSideEffect,
    HttpSideEffect,
    SshSideEffect,
    TestCase,
)
from .db_assert import assert_db_side_effect
from .hoverfly_journal import clear_journal, match_http_side_effect
from .ssh_journal import clear_ssh_journal, match_ssh_side_effect

TERMINAL_STATUSES = {"completed", "cancelled", "error", "suspended"}


@dataclass
class AssertionResult:
    index: int
    kind: str
    status: str  # passed | failed
    expected: str
    got: int
    explain: str = ""


@dataclass
class CaseResult:
    bp: str
    case: str
    run_id: str | None
    status: str  # passed | failed | error | timeout
    process_status: str | None = None
    assertions: list[AssertionResult] = field(default_factory=list)
    error: str = ""


@dataclass
class RunnerContext:
    hoverfly_admin: str
    ssh_replay_journal: str
    sandbox_db_dsn: str
    pdm_api_base: str
    pdm_api_key: str  # MUST be a superuser token
    cli_bypass_secret: str = ""
    ssh_override_dir: str = ""


def _headers(ctx: RunnerContext) -> dict[str, str]:
    h = {"Authorization": f"Token {ctx.pdm_api_key}"}
    if ctx.cli_bypass_secret:
        h["X-Pdm-Cli-Bypass"] = ctx.cli_bypass_secret
    return h


def _resolve_bp_id(ctx: RunnerContext, bp_slug: str) -> int:
    """slug → numeric id via list-filter."""
    r = httpx.get(
        f"{ctx.pdm_api_base}/api/business-processes/",
        params={"slug": bp_slug},
        headers=_headers(ctx),
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    results = data.get("results", data) if isinstance(data, dict) else data
    for item in results:
        if item.get("slug") == bp_slug:
            return int(item["id"])
    raise ValueError(f"BP slug not found in sandbox: {bp_slug}")


def _resolve_entity_type_id(ctx: RunnerContext, type_value) -> int:
    if isinstance(type_value, int):
        return type_value
    r = httpx.get(
        f"{ctx.pdm_api_base}/api/entity-types/",
        params={"name": type_value},
        headers=_headers(ctx),
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    results = data.get("results", data) if isinstance(data, dict) else data
    for item in results:
        if item.get("name") == type_value:
            return int(item["id"])
    raise ValueError(f"entity_type not found: {type_value}")


def _create_entity(ctx: RunnerContext, tc: TestCase) -> int:
    """Create entity via POST /api/entities/, return id."""
    assert tc.entity is not None  # caller guarantees this
    type_id = _resolve_entity_type_id(ctx, tc.entity.type)
    r = httpx.post(
        f"{ctx.pdm_api_base}/api/entities/",
        headers=_headers(ctx),
        json={"entity_type": type_id, "data": tc.entity.fields},
        timeout=15,
    )
    r.raise_for_status()
    return int(r.json()["id"])


def _start_bp(ctx: RunnerContext, bp_id: int, entity_id: int, tc: TestCase) -> str:
    r = httpx.post(
        f"{ctx.pdm_api_base}/api/business-processes/{bp_id}/start_for_entity/",
        headers=_headers(ctx),
        json={
            "entity_id": entity_id,
            "additional_entities": tc.additional_entities,
        },
        timeout=30,
    )
    r.raise_for_status()
    return str(r.json()["id"])


def _poll(ctx: RunnerContext, run_id: str, deadline: float) -> dict | None:
    while time.time() < deadline:
        r = httpx.get(
            f"{ctx.pdm_api_base}/api/process-instances/{run_id}/",
            headers=_headers(ctx),
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") in TERMINAL_STATUSES:
            return data
        time.sleep(0.5)
    return None


def _cancel(ctx: RunnerContext, run_id: str) -> None:
    """Best-effort PATCH status=cancelled (used on timeout)."""
    try:
        httpx.patch(
            f"{ctx.pdm_api_base}/api/process-instances/{run_id}/",
            headers=_headers(ctx),
            json={"status": "cancelled"},
            timeout=10,
        )
    except Exception:
        pass


def _check_count(matches: int, eff) -> tuple[str, str, str]:
    if matches < eff.min_count:
        return (
            "failed",
            f">={eff.min_count}",
            f"got {matches} matches, expected >= {eff.min_count}",
        )
    if eff.max_count is not None and matches > eff.max_count:
        return (
            "failed",
            f"<={eff.max_count}",
            f"got {matches} matches, expected <= {eff.max_count}",
        )
    expected = f">={eff.min_count}" + (
        f", <={eff.max_count}" if eff.max_count is not None else ""
    )
    return ("passed", expected, "")


def run_case(tc: TestCase, bp_slug: str, ctx: RunnerContext) -> CaseResult:
    result = CaseResult(bp=bp_slug, case=tc.name, run_id=None, status="error")
    try:
        clear_journal(ctx.hoverfly_admin)
        clear_ssh_journal(ctx.ssh_replay_journal)
        bp_id = _resolve_bp_id(ctx, bp_slug)
        entity_id = (
            tc.entity_id if tc.entity_id is not None else _create_entity(ctx, tc)
        )
        result.run_id = _start_bp(ctx, bp_id, entity_id, tc)
        deadline = time.time() + tc.timeout_sec
        outcome = _poll(ctx, result.run_id, deadline)
        if outcome is None:
            _cancel(ctx, result.run_id)
            result.status = "timeout"
            result.process_status = "cancelled"
            return result
        result.process_status = outcome.get("status")
        if result.process_status != tc.expect.final_status:
            result.status = "failed"
            result.assertions.append(
                AssertionResult(
                    index=-1,
                    kind="final_status",
                    status="failed",
                    expected=tc.expect.final_status,
                    got=0,
                    explain=(
                        f"status: expected {tc.expect.final_status}, "
                        f"got {result.process_status}"
                    ),
                )
            )
            return result
        for i, eff in enumerate(tc.expect.side_effects):
            if isinstance(eff, HttpSideEffect):
                matches = len(match_http_side_effect(ctx.hoverfly_admin, eff))
            elif isinstance(eff, SshSideEffect):
                matches = len(match_ssh_side_effect(ctx.ssh_replay_journal, eff))
            elif isinstance(eff, DbSideEffect):
                matches = assert_db_side_effect(ctx.sandbox_db_dsn, eff)
            else:
                raise ValueError(f"unknown kind {eff!r}")
            status, expected_str, explain = _check_count(matches, eff)
            result.assertions.append(
                AssertionResult(
                    index=i,
                    kind=eff.kind,
                    status=status,
                    expected=expected_str,
                    got=matches,
                    explain=explain,
                )
            )
        result.status = (
            "failed"
            if any(a.status == "failed" for a in result.assertions)
            else "passed"
        )
    except Exception as e:
        result.status = "error"
        result.error = repr(e)
    return result
