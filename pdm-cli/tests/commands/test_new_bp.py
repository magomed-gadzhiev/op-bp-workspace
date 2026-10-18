"""Tests for `pdm new-bp` — scaffold a new business-process skeleton.

Mirrors the CliRunner + obj={"cwd": tmp_path} convention of test_scaffold_install.py.
Covers contracts/new-bp-cli.md §"Test obligations" (FR-016 – FR-022, SC-004, SC-006).
"""
from pathlib import Path

from click.testing import CliRunner

from pdm_cli.cli import main
from pdm_cli.repo import read_process


def _bp_dir(root: Path, slug: str) -> Path:
    return root / "processes" / slug


def test_new_bp_creates_valid_skeleton(tmp_path: Path):
    """Happy path: all five sub-components exist and `pdm validate` exits 0."""
    runner = CliRunner()
    result = runner.invoke(main, ["new-bp", "demo-bp"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output

    bp = _bp_dir(tmp_path, "demo-bp")
    assert (bp / "manifest.yaml").is_file(), "manifest.yaml missing"
    assert (bp / "tasks").is_dir(), "tasks/ missing"
    assert (bp / "tasks" / "placeholder.yaml").is_file(), "placeholder task missing"
    assert (bp / "fixtures").is_dir(), "fixtures/ missing"
    assert (bp / "tests").is_dir(), "tests/ missing"
    assert (bp / "decisions").is_dir(), "decisions/ missing"

    # The generated skeleton must validate with zero manual edits (SC-004).
    validate = runner.invoke(main, ["validate", "--bp", "demo-bp"], obj={"cwd": tmp_path})
    assert validate.exit_code == 0, validate.output


def test_new_bp_manifest_fields(tmp_path: Path):
    """Manifest is populated: version=1, status=draft, expected slug/name."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["new-bp", "demo-bp", "--name", "Demo Process", "--description", "A demo."],
        obj={"cwd": tmp_path},
    )
    assert result.exit_code == 0, result.output

    process = read_process(tmp_path, "demo-bp")
    assert process.manifest.slug == "demo-bp"
    assert process.manifest.name == "Demo Process"
    assert process.manifest.description == "A demo."
    assert process.manifest.version == 1
    assert process.manifest.status == "draft"
    assert process.manifest.owner is None
    # Placeholder task present so the BP is non-empty (FR-017).
    assert len(process.tasks) == 1
    assert process.tasks[0].slug == "placeholder"


def test_new_bp_default_name_is_humanized_slug(tmp_path: Path):
    """With no --name, the manifest name is a humanized form of the slug."""
    runner = CliRunner()
    result = runner.invoke(main, ["new-bp", "demo-bp"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    process = read_process(tmp_path, "demo-bp")
    assert process.manifest.name == "Demo Bp"


def test_new_bp_refuses_existing(tmp_path: Path):
    """Second run on the same slug exits non-zero and leaves the original untouched."""
    runner = CliRunner()
    first = runner.invoke(main, ["new-bp", "demo-bp"], obj={"cwd": tmp_path})
    assert first.exit_code == 0, first.output

    manifest_path = _bp_dir(tmp_path, "demo-bp") / "manifest.yaml"
    original = manifest_path.read_bytes()

    second = runner.invoke(main, ["new-bp", "demo-bp"], obj={"cwd": tmp_path})
    assert second.exit_code != 0, "duplicate slug must be refused"
    # Original manifest is byte-for-byte unchanged (no overwrite, FR-019).
    assert manifest_path.read_bytes() == original


def test_new_bp_rejects_invalid_slug(tmp_path: Path):
    """A bad slug exits non-zero and creates nothing on disk (FR-020)."""
    runner = CliRunner()
    result = runner.invoke(main, ["new-bp", "Bad Slug"], obj={"cwd": tmp_path})
    assert result.exit_code != 0, "invalid slug must be rejected"
    # Nothing was written — not even the processes/ root.
    assert not (tmp_path / "processes").exists()


def test_new_bp_follows_conventions(tmp_path: Path):
    """Uses --target-dir / ctx.obj['cwd'] like sibling commands."""
    target = tmp_path / "client-repo"
    target.mkdir()
    runner = CliRunner()
    # --target-dir overrides ctx.obj["cwd"].
    result = runner.invoke(
        main,
        ["new-bp", "demo-bp", "--target-dir", str(target)],
        obj={"cwd": tmp_path},
    )
    assert result.exit_code == 0, result.output
    assert (_bp_dir(target, "demo-bp") / "manifest.yaml").is_file()
    # Nothing leaked into ctx.obj["cwd"] when --target-dir is given.
    assert not (_bp_dir(tmp_path, "demo-bp")).exists()
