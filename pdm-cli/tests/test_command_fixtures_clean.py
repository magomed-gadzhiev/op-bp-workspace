"""E16 US2 — `pdm fixtures clean` removes fixtures no test case references.

Covers contracts C-C1 … C-C8 (specs/036-fixture-hygiene/contracts/fixtures-clean.md).
"""
from pathlib import Path

from click.testing import CliRunner

from pdm_cli.cli import main


def _bp(tmp_path: Path) -> Path:
    (tmp_path / "pdm.config.yaml").write_text(
        "endpoints:\n  sandbox: http://x\n", encoding="utf-8"
    )
    bp = tmp_path / "processes" / "demo-bp"
    (bp / "fixtures").mkdir(parents=True)
    (bp / "tests").mkdir(parents=True)
    (bp / "manifest.yaml").write_text(
        "slug: demo-bp\nname: D\nversion: 1\nstatus: draft\n", encoding="utf-8"
    )
    return bp


def _fix(bp: Path, stem: str, version: int = 1) -> Path:
    p = bp / "fixtures" / f"{stem}.yaml"
    case = stem.split("-", 1)[1]
    p.write_text(f"name: {case}\nversion: {version}\nmatchers: []\n", encoding="utf-8")
    return p


def _archive(bp: Path, stem: str, version: int) -> Path:
    p = bp / "fixtures" / "_archive" / stem / f"v{version}.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"name: x\nversion: {version}\nmatchers: []\n", encoding="utf-8")
    return p


def _case(bp: Path, name: str, fixtures: list[str]) -> None:
    fx = "\n".join(f"  - {f}" for f in fixtures)
    (bp / "tests" / f"{name}.yaml").write_text(
        f"name: {name}\nfixtures:\n{fx}\nentity_id: 1\n"
        f"expect:\n  final_status: completed\n",
        encoding="utf-8",
    )


def _clean(repo: Path, *args) -> object:
    return CliRunner().invoke(
        main, ["fixtures", "clean", "--bp", "demo-bp", *args], obj={"cwd": repo}
    )


def test_clean_dry_run_lists_but_keeps(tmp_path):  # C-C1 / C-C2
    bp = _bp(tmp_path)
    used = _fix(bp, "http-used")
    orphan = _fix(bp, "http-orphan")
    _case(bp, "smoke", ["http-used"])
    r = _clean(tmp_path, "--dry-run")
    assert r.exit_code == 0, r.output
    assert "http-orphan" in r.output
    assert "http-used" not in r.output.replace("http-used", "")  # used not a candidate
    assert orphan.is_file() and used.is_file()  # nothing deleted


def test_clean_deletes_only_unused(tmp_path):  # C-C3
    bp = _bp(tmp_path)
    used = _fix(bp, "http-used")
    orphan = _fix(bp, "http-orphan")
    _case(bp, "smoke", ["http-used"])
    r = _clean(tmp_path)
    assert r.exit_code == 0, r.output
    assert not orphan.is_file()
    assert used.is_file()


def test_clean_removes_archive_subtree(tmp_path):  # C-C4
    bp = _bp(tmp_path)
    _fix(bp, "http-orphan", version=2)
    arch = _archive(bp, "http-orphan", 1)
    _case(bp, "smoke", [])  # nothing referenced
    r = _clean(tmp_path)
    assert r.exit_code == 0, r.output
    assert not arch.is_file()
    assert not (bp / "fixtures" / "_archive" / "http-orphan").exists()


def test_clean_keeps_fixture_referenced_only_via_pin(tmp_path):  # C-C5
    bp = _bp(tmp_path)
    pinned = _fix(bp, "http-pinned", version=2)
    _archive(bp, "http-pinned", 1)
    _case(bp, "smoke", ["http-pinned@2"])
    r = _clean(tmp_path)
    assert r.exit_code == 0, r.output
    assert pinned.is_file()  # stem referenced via pin → used


def test_clean_all_used_deletes_nothing(tmp_path):  # C-C6
    bp = _bp(tmp_path)
    a = _fix(bp, "http-a")
    b = _fix(bp, "ssh-b")
    _case(bp, "smoke", ["http-a", "ssh-b"])
    r = _clean(tmp_path)
    assert r.exit_code == 0, r.output
    assert a.is_file() and b.is_file()


def test_clean_no_fixtures_clear_message(tmp_path):  # C-C7
    _bp(tmp_path)
    r = _clean(tmp_path)
    assert r.exit_code == 0
    assert "Traceback" not in r.output


def test_clean_nonexistent_bp_exit_zero(tmp_path):  # C-C7 (bad BP)
    (tmp_path / "pdm.config.yaml").write_text("endpoints:\n  sandbox: http://x\n", encoding="utf-8")
    r = CliRunner().invoke(main, ["fixtures", "clean", "--bp", "ghost"], obj={"cwd": tmp_path})
    assert r.exit_code == 0
    assert "Traceback" not in r.output


def test_clean_http_and_ssh_uniform(tmp_path):  # C-C8
    bp = _bp(tmp_path)
    http_orphan = _fix(bp, "http-orphan")
    ssh_orphan = _fix(bp, "ssh-orphan")
    _case(bp, "smoke", [])
    r = _clean(tmp_path)
    assert r.exit_code == 0, r.output
    assert not http_orphan.is_file()
    assert not ssh_orphan.is_file()
