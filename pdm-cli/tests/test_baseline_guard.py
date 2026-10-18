"""E17 — unit tests for the pure baseline-guard decision logic (US2).

Spec: specs/037-test-baseline-cleanup/spec.md (FR-006/FR-007/FR-008/FR-009).
"""

from tests.baseline_guard import evaluate_baseline


def test_clean_baseline_no_violations():
    # count == baseline, every skip reasoned, count check on → OK
    assert evaluate_baseline(19, 19, [], check_count=True) == []


def test_count_drift_flagged_when_checking():
    out = evaluate_baseline(21, 19, [], check_count=True)
    assert len(out) == 1
    assert "BASELINE DRIFT" in out[0]
    assert "+2" in out[0]


def test_count_drift_silent_when_not_checking():
    # partial run skips more than baseline-context but check is off → silent
    assert evaluate_baseline(21, 19, [], check_count=False) == []


def test_reasonless_skip_always_flagged():
    # reason rule fires regardless of check_count
    off = evaluate_baseline(5, 19, ["tests/x.py::test_a"], check_count=False)
    on = evaluate_baseline(5, 19, ["tests/x.py::test_a"], check_count=True)
    assert off == ["SKIP WITHOUT REASON: tests/x.py::test_a"]
    assert on == ["SKIP WITHOUT REASON: tests/x.py::test_a"]


def test_both_rules_combine():
    out = evaluate_baseline(20, 19, ["tests/x.py::test_a"], check_count=True)
    assert any("BASELINE DRIFT" in v for v in out)
    assert any("SKIP WITHOUT REASON" in v for v in out)
    assert len(out) == 2
