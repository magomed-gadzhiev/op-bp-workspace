"""E17 test-baseline drift guard — pure decision logic (no pytest imports).

The conftest hooks collect skipped-test data during a run and delegate the
verdict to :func:`evaluate_baseline`, which is kept dependency-free so it can be
unit-tested in isolation. See specs/037-test-baseline-cleanup/ and docs/TESTING.md.
"""

from __future__ import annotations


def evaluate_baseline(
    skipped_count: int,
    baseline: int,
    reasonless: list[str],
    *,
    check_count: bool,
) -> list[str]:
    """Return a list of human-readable baseline violations (empty == OK).

    Two independent rules:

    * **reason rule** (always on): every skipped test must carry a non-empty
      reason. Each ``reasonless`` node id yields one violation. This is
      universally correct and safe even on partial test selections.
    * **count rule** (opt-in via ``check_count``): the number of skipped tests
      must not exceed the recorded ``baseline``. Gated so that running a subset
      of the suite — which legitimately skips fewer tests — never trips it; the
      canonical baseline command opts in.
    """
    violations: list[str] = []
    if check_count and skipped_count > baseline:
        delta = skipped_count - baseline
        violations.append(
            f"BASELINE DRIFT: expected <= {baseline} skipped, got {skipped_count} "
            f"(+{delta}). If this is intentional, update PDM_SKIP_BASELINE and "
            f"docs/TESTING.md."
        )
    for nodeid in reasonless:
        violations.append(f"SKIP WITHOUT REASON: {nodeid}")
    return violations
