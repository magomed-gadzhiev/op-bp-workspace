"""E16 fixture hygiene — `pdm_cli.fixtures.versioning` ref parsing + path resolution.

Covers contracts C-V4 … C-V14 (specs/036-fixture-hygiene/contracts/versioning.md).
"""
from pathlib import Path

import pytest

from pdm_cli.fixtures.versioning import (
    parse_ref,
    resolve_fixture_file,
    available_versions,
    archive_active,
)


def _write(path: Path, name: str, version: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"name: {name}\nversion: {version}\nmatchers: []\n", encoding="utf-8")


# --------------------------------------------------------------------------- parse_ref


def test_parse_ref_bare():  # C-V4
    assert parse_ref("http-happy") == ("http-happy", None)


def test_parse_ref_pinned():  # C-V5
    assert parse_ref("http-happy@2") == ("http-happy", 2)


def test_parse_ref_splits_on_last_at():  # C-V6
    assert parse_ref("ssh-deploy@10") == ("ssh-deploy", 10)
    assert parse_ref("weird@name@3") == ("weird@name", 3)


def test_parse_ref_nonpositive_or_nonint_kept_as_stem():  # C-V7
    # Right side that is not a positive int is treated as part of the name (defensive).
    assert parse_ref("http-happy@0") == ("http-happy@0", None)
    assert parse_ref("http-happy@abc") == ("http-happy@abc", None)
    assert parse_ref("http-happy@-1") == ("http-happy@-1", None)


# --------------------------------------------------------------------- resolve_fixture_file


def test_resolve_bare_to_active(tmp_path):  # C-V8
    bp = tmp_path / "demo"
    active = bp / "fixtures" / "http-happy.yaml"
    _write(active, "happy", 1)
    assert resolve_fixture_file(bp, "http-happy") == active


def test_resolve_pinned_equal_to_active(tmp_path):  # C-V9
    bp = tmp_path / "demo"
    active = bp / "fixtures" / "http-happy.yaml"
    _write(active, "happy", 3)
    assert resolve_fixture_file(bp, "http-happy@3") == active


def test_resolve_pinned_older_to_archive(tmp_path):  # C-V10
    bp = tmp_path / "demo"
    _write(bp / "fixtures" / "http-happy.yaml", "happy", 3)
    archived = bp / "fixtures" / "_archive" / "http-happy" / "v1.yaml"
    _write(archived, "happy", 1)
    assert resolve_fixture_file(bp, "http-happy@1") == archived


def test_resolve_missing_version_errors_with_available(tmp_path):  # C-V11
    bp = tmp_path / "demo"
    _write(bp / "fixtures" / "http-happy.yaml", "happy", 2)
    _write(bp / "fixtures" / "_archive" / "http-happy" / "v1.yaml", "happy", 1)
    with pytest.raises(Exception) as ei:
        resolve_fixture_file(bp, "http-happy@5")
    msg = str(ei.value)
    assert "http-happy" in msg
    assert "1" in msg and "2" in msg  # available versions listed


def test_resolve_bare_missing_active_errors(tmp_path):  # C-V12
    bp = tmp_path / "demo"
    (bp / "fixtures").mkdir(parents=True)
    with pytest.raises(Exception):
        resolve_fixture_file(bp, "http-ghost")


# --------------------------------------------------------------------- available_versions


def test_available_versions_active_plus_archive_sorted_deduped(tmp_path):  # C-V13
    bp = tmp_path / "demo"
    _write(bp / "fixtures" / "http-happy.yaml", "happy", 3)
    _write(bp / "fixtures" / "_archive" / "http-happy" / "v1.yaml", "happy", 1)
    _write(bp / "fixtures" / "_archive" / "http-happy" / "v2.yaml", "happy", 2)
    assert available_versions(bp, "http-happy") == [1, 2, 3]


def test_available_versions_empty_when_nothing_exists(tmp_path):  # C-V13 (empty)
    bp = tmp_path / "demo"
    assert available_versions(bp, "http-nope") == []


# ------------------------------------------------------------------------- archive_active


def test_archive_active_copies_to_versioned_path(tmp_path):  # C-V14
    bp = tmp_path / "demo"
    _write(bp / "fixtures" / "http-happy.yaml", "happy", 2)
    dest = archive_active(bp, "http-happy")
    assert dest == bp / "fixtures" / "_archive" / "http-happy" / "v2.yaml"
    assert dest.is_file()
    assert "version: 2" in dest.read_text(encoding="utf-8")
