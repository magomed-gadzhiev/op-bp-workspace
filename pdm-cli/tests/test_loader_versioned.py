"""E16 US1 — loader resolves ``<name>@N`` to active or archived content.

Uses the SSH path (writes an override file, no network) to assert which on-disk
content the loader actually picked up.
"""
from pathlib import Path
from unittest.mock import MagicMock

from pdm_cli.fixtures.loader import load_fixtures_for_case


def _write_ssh(path: Path, name: str, version: int, stdout: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"name: {name}\n"
        f"version: {version}\n"
        f"matchers:\n"
        f"  - request:\n"
        f"      host: h\n"
        f"      user: u\n"
        f"      command_matches: ls\n"
        f"    response:\n"
        f'      stdout: "{stdout}"\n'
        f"      exit_code: 0\n",
        encoding="utf-8",
    )


def _ctx(tmp_path: Path) -> MagicMock:
    return MagicMock(hoverfly_admin="http://x", ssh_override_dir=str(tmp_path / "ovr"))


def _written(ctx) -> str:
    return (Path(ctx.ssh_override_dir) / "fixture-ssh-deploy.yaml").read_text(encoding="utf-8")


def test_loader_bare_ref_resolves_active(tmp_path):  # C-V8
    bp = tmp_path / "processes" / "demo"
    _write_ssh(bp / "fixtures" / "ssh-deploy.yaml", "deploy", 2, "active-v2")
    ctx = _ctx(tmp_path)
    load_fixtures_for_case(MagicMock(fixtures=["ssh-deploy"]), bp, ctx)
    assert "active-v2" in _written(ctx)


def test_loader_pinned_old_ref_resolves_archive(tmp_path):  # C-V10 / FR-006
    bp = tmp_path / "processes" / "demo"
    _write_ssh(bp / "fixtures" / "ssh-deploy.yaml", "deploy", 2, "active-v2")
    _write_ssh(bp / "fixtures" / "_archive" / "ssh-deploy" / "v1.yaml", "deploy", 1, "frozen-v1")
    ctx = _ctx(tmp_path)
    load_fixtures_for_case(MagicMock(fixtures=["ssh-deploy@1"]), bp, ctx)
    written = _written(ctx)
    assert "frozen-v1" in written
    assert "active-v2" not in written


def test_loader_pin_keeps_archived_after_active_advances(tmp_path):  # SC-005
    bp = tmp_path / "processes" / "demo"
    # Active has already advanced to v3; v1 lives frozen in the archive.
    _write_ssh(bp / "fixtures" / "ssh-deploy.yaml", "deploy", 3, "active-v3")
    _write_ssh(bp / "fixtures" / "_archive" / "ssh-deploy" / "v1.yaml", "deploy", 1, "frozen-v1")
    ctx = _ctx(tmp_path)
    load_fixtures_for_case(MagicMock(fixtures=["ssh-deploy@1"]), bp, ctx)
    assert "frozen-v1" in _written(ctx)
