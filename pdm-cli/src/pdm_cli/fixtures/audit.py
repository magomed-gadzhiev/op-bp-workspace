"""E16 fixture hygiene — pure helpers for `pdm fixtures audit` / `clean`.

No CLI, no side effects: scan a BP's fixtures and test cases and report. Reads YAML
raw (version / recorded_at / fixture refs only) to stay decoupled from the fixture
models and tolerant of empty-matcher fixtures.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ruamel.yaml import YAML

from .versioning import parse_ref, staleness


def _load_raw(path: Path) -> dict:
    y = YAML(typ="safe")
    with Path(path).open("r", encoding="utf-8") as f:
        return y.load(f) or {}


def _fmt_recorded_at(value) -> str:
    """Render recorded_at for display. The YAML loader may hand back a datetime."""
    if value in (None, ""):
        return "unknown"
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def active_fixture_files(bp_dir: Path) -> list[Path]:
    """Active (latest) fixture files of both protocols — never the ``_archive`` subtree."""
    fdir = Path(bp_dir) / "fixtures"
    if not fdir.is_dir():
        return []
    return sorted([*fdir.glob("http-*.yaml"), *fdir.glob("ssh-*.yaml")])


def referenced_stems(bp_dir: Path) -> set[str]:
    """Collect every fixture stem referenced by a BP test case (``@N`` stripped)."""
    stems: set[str] = set()
    tests_dir = Path(bp_dir) / "tests"
    if not tests_dir.is_dir():
        return stems
    for path in sorted(tests_dir.glob("*.yaml")):
        try:
            data = _load_raw(path)
        except Exception:
            continue
        for ref in data.get("fixtures", []) or []:
            stem, _ = parse_ref(str(ref))
            stems.add(stem)
    return stems


def audit_rows(bp_dir: Path, weeks: int, now: datetime | None = None) -> list[dict]:
    """One row per active fixture: stem, version, recorded_at, age, status (D6)."""
    rows: list[dict] = []
    for f in active_fixture_files(bp_dir):
        try:
            data = _load_raw(f)
        except Exception:
            data = {}
        recorded_at = data.get("recorded_at")
        age, status = staleness(recorded_at, weeks, now)
        rows.append(
            {
                "fixture": f.stem,
                "version": data.get("version", 1),
                "recorded_at": _fmt_recorded_at(recorded_at),
                "age": age,
                "status": status,
            }
        )
    return rows
