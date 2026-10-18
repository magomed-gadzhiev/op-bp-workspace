"""Tests for `pdm scaffold install`."""
from pathlib import Path

from click.testing import CliRunner

from pdm_cli.cli import main


REQUIRED_SKILLS = [
    "pdm-create-process.md",
    "pdm-debug-failed-run.md",
    "pdm-debug-ssh.md",
    "pdm-edit-process.md",
    "pdm-explain-bp.md",
    "pdm-promote-release.md",
    "pdm-record-fixture.md",
    "pdm-triage-feedback.md",
    "pdm-weekly-review.md",
]


def _skill_dir(tmp_path: Path) -> Path:
    return tmp_path / ".claude" / "skills" / "pdm"


def test_install_adds_missing_files_only(tmp_path: Path):
    skill_dir = _skill_dir(tmp_path)
    skill_dir.mkdir(parents=True)
    custom = "CUSTOM CONTENT — do not overwrite"
    pre = skill_dir / "pdm-promote-release.md"
    pre.write_text(custom, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["scaffold", "install"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output

    for name in REQUIRED_SKILLS:
        assert (skill_dir / name).is_file(), f"missing required skill {name}"

    # Pre-existing file content preserved.
    assert pre.read_text(encoding="utf-8") == custom


def test_install_force_overwrites_all(tmp_path: Path):
    skill_dir = _skill_dir(tmp_path)
    skill_dir.mkdir(parents=True)
    custom = "CUSTOM CONTENT — should be overwritten"
    pre = skill_dir / "pdm-promote-release.md"
    pre.write_text(custom, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        main, ["scaffold", "install", "--force"], obj={"cwd": tmp_path}
    )
    assert result.exit_code == 0, result.output

    for name in REQUIRED_SKILLS:
        assert (skill_dir / name).is_file(), f"missing required skill {name}"

    # Pre-existing file replaced by package content (no longer custom).
    assert pre.read_text(encoding="utf-8") != custom


def test_install_creates_missing_directory(tmp_path: Path):
    # No .claude/ at all.
    assert not (tmp_path / ".claude").exists()

    runner = CliRunner()
    result = runner.invoke(main, ["scaffold", "install"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output

    skill_dir = _skill_dir(tmp_path)
    assert skill_dir.is_dir(), "scaffold install must create .claude/skills/pdm/"
    for name in REQUIRED_SKILLS:
        assert (skill_dir / name).is_file(), f"missing required skill {name}"
