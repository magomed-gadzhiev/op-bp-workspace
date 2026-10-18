"""E16 US2 — `pdm fixtures audit` reports version / date / staleness.

Covers contracts C-A1 … C-A7 (specs/036-fixture-hygiene/contracts/fixtures-audit.md).
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from click.testing import CliRunner

from pdm_cli.cli import main


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


_NOW = datetime.now(timezone.utc)
FRESH = _iso(_NOW - timedelta(days=1))      # 0 weeks
MID = _iso(_NOW - timedelta(days=35))       # 5 weeks
OLD = _iso(_NOW - timedelta(days=200))      # ~28 weeks
FUTURE = _iso(_NOW + timedelta(days=365))


def _bp(tmp_path: Path) -> Path:
    (tmp_path / "pdm.config.yaml").write_text(
        "endpoints:\n  sandbox: http://x\n", encoding="utf-8"
    )
    bp = tmp_path / "processes" / "demo-bp"
    (bp / "fixtures").mkdir(parents=True)
    (bp / "manifest.yaml").write_text(
        "slug: demo-bp\nname: D\nversion: 1\nstatus: draft\n", encoding="utf-8"
    )
    return bp


def _fix(bp: Path, stem: str, version: int = 1, recorded_at: str | None = None) -> None:
    ra = f"recorded_at: {recorded_at}\n" if recorded_at else ""
    case = stem.split("-", 1)[1]
    (bp / "fixtures" / f"{stem}.yaml").write_text(
        f"name: {case}\nversion: {version}\n{ra}matchers: []\n", encoding="utf-8"
    )


def _audit(repo: Path, *args) -> object:
    return CliRunner().invoke(
        main, ["fixtures", "audit", "--bp", "demo-bp", *args], obj={"cwd": repo}
    )


def test_audit_one_row_per_active_fixture_http_and_ssh(tmp_path):  # C-A1
    bp = _bp(tmp_path)
    _fix(bp, "http-fresh", version=2, recorded_at=FRESH)
    _fix(bp, "ssh-old", version=1, recorded_at=OLD)
    r = _audit(tmp_path)
    assert r.exit_code == 0, r.output
    assert "http-fresh" in r.output
    assert "ssh-old" in r.output
    assert "ok" in r.output


def test_audit_marks_stale_past_default_12_weeks(tmp_path):  # C-A2
    bp = _bp(tmp_path)
    _fix(bp, "http-old", recorded_at=OLD)
    r = _audit(tmp_path)
    assert r.exit_code == 0
    assert "stale" in r.output


def test_audit_weeks_4_tightens_threshold(tmp_path):  # C-A3
    bp = _bp(tmp_path)
    _fix(bp, "http-mid", recorded_at=MID)  # 5 weeks
    ok_default = _audit(tmp_path)
    # Ignore the title line (it mentions the "stale threshold").
    body = "\n".join(l for l in ok_default.output.splitlines() if "threshold" not in l)
    assert "stale" not in body  # ok at 12 weeks
    stale_tight = _audit(tmp_path, "--weeks", "4")
    tight_body = "\n".join(l for l in stale_tight.output.splitlines() if "threshold" not in l)
    assert "stale" in tight_body  # stale at 4 weeks


def test_audit_unknown_date_is_stale(tmp_path):  # C-A4
    bp = _bp(tmp_path)
    _fix(bp, "http-legacy", recorded_at=None)
    r = _audit(tmp_path)
    assert r.exit_code == 0
    assert "stale (unknown date)" in r.output


def test_audit_future_date_not_stale_flagged(tmp_path):  # C-A5
    bp = _bp(tmp_path)
    _fix(bp, "http-future", recorded_at=FUTURE)
    r = _audit(tmp_path)
    assert r.exit_code == 0
    assert "future date?" in r.output


def test_audit_no_fixtures_clear_message(tmp_path):  # C-A6 (empty BP)
    _bp(tmp_path)
    r = _audit(tmp_path)
    assert r.exit_code == 0
    assert "no fixtures" in r.output.lower() or "no active fixtures" in r.output.lower()


def test_audit_nonexistent_bp_no_traceback(tmp_path):  # C-A6 (bad BP)
    (tmp_path / "pdm.config.yaml").write_text("endpoints:\n  sandbox: http://x\n", encoding="utf-8")
    r = CliRunner().invoke(main, ["fixtures", "audit", "--bp", "ghost"], obj={"cwd": tmp_path})
    assert r.exit_code == 0
    assert "Traceback" not in r.output


def test_audit_always_exit_zero_when_all_fresh(tmp_path):  # C-A7
    bp = _bp(tmp_path)
    _fix(bp, "http-fresh", recorded_at=FRESH)
    r = _audit(tmp_path)
    assert r.exit_code == 0
