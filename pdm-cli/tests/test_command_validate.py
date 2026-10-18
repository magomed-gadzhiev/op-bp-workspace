import shutil
from pathlib import Path

from click.testing import CliRunner

from pdm_cli.cli import main


SAMPLE = Path(__file__).parent / "fixtures" / "sample-repo"


def _stage_repo(tmp_path):
    """Copy sample fixture into tmp_path and add minimal pdm.config.yaml."""
    shutil.copytree(SAMPLE, tmp_path, dirs_exist_ok=True)
    (tmp_path / "pdm.config.yaml").write_text(
        "endpoints:\n  prod: http://x\n  sandbox: http://y\n", encoding="utf-8"
    )
    return tmp_path


def test_validate_passes_on_clean_sample_repo(tmp_path):
    _stage_repo(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["validate"], obj={"cwd": tmp_path})
    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_validate_only_specified_bp(tmp_path):
    _stage_repo(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["validate", "--bp", "payroll"], obj={"cwd": tmp_path})
    assert result.exit_code == 0
    assert "1 process" in result.output


def test_validate_fails_on_invalid_manifest(tmp_path):
    _stage_repo(tmp_path)
    bad = tmp_path / "processes" / "payroll" / "manifest.yaml"
    bad.write_text(
        "slug: WRONG-UPPER\nname: x\nversion: 1\nstatus: draft\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(main, ["validate"], obj={"cwd": tmp_path})
    assert result.exit_code == 1
    # Either the slug pattern or the violation should be mentioned
    assert "WRONG-UPPER" in result.output or "slug" in result.output


def test_validate_fails_on_invalid_status(tmp_path):
    _stage_repo(tmp_path)
    bad = tmp_path / "processes" / "payroll" / "manifest.yaml"
    bad.write_text(
        "slug: payroll\nname: P\nversion: 1\nstatus: weird-status\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(main, ["validate"], obj={"cwd": tmp_path})
    assert result.exit_code == 1


def test_validate_no_processes_warns_but_succeeds(tmp_path):
    """Empty repo (no processes/) — succeeds with warning."""
    (tmp_path / "pdm.config.yaml").write_text(
        "endpoints:\n  prod: http://x\n", encoding="utf-8"
    )
    runner = CliRunner()
    result = runner.invoke(main, ["validate"], obj={"cwd": tmp_path})
    assert result.exit_code == 0
    assert "No processes" in result.output


def test_validate_specific_unknown_bp_fails(tmp_path):
    """--bp pointing to non-existent BP fails (FileNotFoundError surfaces)."""
    _stage_repo(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["validate", "--bp", "nope"], obj={"cwd": tmp_path})
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Fixture validation tests
# ---------------------------------------------------------------------------


def _stage_repo_with_fixtures(tmp_path: Path, http_yaml: str = None, ssh_yaml: str = None) -> Path:
    """Minimal repo with pdm.config.yaml + one BP + optional fixture files."""
    (tmp_path / "pdm.config.yaml").write_text(
        "endpoints:\n  sandbox: http://x\n", encoding="utf-8"
    )
    (tmp_path / "processes" / "demo-bp").mkdir(parents=True)
    (tmp_path / "processes" / "demo-bp" / "manifest.yaml").write_text(
        "slug: demo-bp\nname: D\nversion: 1\nstatus: draft\n", encoding="utf-8"
    )
    fixtures = tmp_path / "processes" / "demo-bp" / "fixtures"
    fixtures.mkdir()
    if http_yaml is not None:
        (fixtures / "http-x.yaml").write_text(http_yaml, encoding="utf-8")
    if ssh_yaml is not None:
        (fixtures / "ssh-x.yaml").write_text(ssh_yaml, encoding="utf-8")
    return tmp_path


def test_validate_passes_on_clean_fixture(tmp_path):
    repo = _stage_repo_with_fixtures(
        tmp_path,
        http_yaml=(
            "name: clean\n"
            "matchers:\n"
            "  - request:\n"
            "      method: GET\n"
            "      url_matches: 'https://x\\.local/y'\n"
            "    response:\n"
            "      status: 200\n"
            "      body: ok\n"
        ),
    )
    r = CliRunner().invoke(main, ["validate"], obj={"cwd": repo})
    assert r.exit_code == 0, r.output


def test_validate_warns_on_suspicious_token_in_fixture(tmp_path):
    repo = _stage_repo_with_fixtures(
        tmp_path,
        http_yaml=(
            "name: tokeny\n"
            "matchers:\n"
            "  - request:\n"
            "      method: GET\n"
            "      url_matches: 'https://x\\.local/y'\n"
            "    response:\n"
            "      status: 200\n"
            "      body: 'Bearer abcdef1234567890'\n"
        ),
    )
    r = CliRunner().invoke(main, ["validate"], obj={"cwd": repo})
    assert r.exit_code == 0, r.output
    assert "PII suspect" in r.output or "Bearer" in r.output


def test_validate_fails_on_malformed_fixture_yaml(tmp_path):
    repo = _stage_repo_with_fixtures(
        tmp_path,
        http_yaml="this: is: not: valid: yaml: at all\n",
    )
    r = CliRunner().invoke(main, ["validate"], obj={"cwd": repo})
    assert r.exit_code != 0


# ---------------------------------------------------------------------------
# E16 US1 — fixture reference resolution checks (FR-007, FR-008, C-V12, SC-002)
# ---------------------------------------------------------------------------


def _write_test_case(bp_path: Path, name: str, fixtures: list[str]) -> None:
    tdir = bp_path / "tests"
    tdir.mkdir(exist_ok=True)
    fx = "\n".join(f"  - {f}" for f in fixtures)
    (tdir / f"{name}.yaml").write_text(
        f"name: {name}\n"
        f"fixtures:\n{fx}\n"
        f"entity_id: 1\n"
        f"expect:\n  final_status: completed\n",
        encoding="utf-8",
    )


def test_validate_errors_on_pinned_missing_version(tmp_path):  # FR-007
    repo = _stage_repo_with_fixtures(
        tmp_path, http_yaml="name: x\nversion: 1\nmatchers: []\n"
    )
    _write_test_case(repo / "processes" / "demo-bp", "smoke", ["http-x@5"])
    r = CliRunner().invoke(main, ["validate"], obj={"cwd": repo})
    assert r.exit_code == 1, r.output
    assert "http-x" in r.output
    assert "1" in r.output  # available versions listed


def test_validate_passes_on_legacy_and_bare_refs(tmp_path):  # FR-008 / SC-002
    repo = _stage_repo_with_fixtures(
        tmp_path, http_yaml="name: x\nmatchers: []\n"  # legacy — no version field
    )
    _write_test_case(repo / "processes" / "demo-bp", "smoke", ["http-x"])
    r = CliRunner().invoke(main, ["validate"], obj={"cwd": repo})
    assert r.exit_code == 0, r.output


def test_validate_errors_on_bare_ref_missing_active(tmp_path):  # C-V12
    repo = _stage_repo_with_fixtures(tmp_path)  # fixtures dir exists, empty
    _write_test_case(repo / "processes" / "demo-bp", "smoke", ["http-ghost"])
    r = CliRunner().invoke(main, ["validate"], obj={"cwd": repo})
    assert r.exit_code == 1, r.output
    assert "http-ghost" in r.output


# ---------------------------------------------------------------------------
# E16 US3 — archive-aware validate (FR-023, SC-002)
# ---------------------------------------------------------------------------


def _write_archived(bp_path: Path, stem: str, version: int, body: str) -> Path:
    p = bp_path / "fixtures" / "_archive" / stem / f"v{version}.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "name: x\n"
        f"version: {version}\n"
        "matchers:\n"
        "  - request:\n"
        "      method: GET\n"
        "      url_matches: 'https://x\\.local/y'\n"
        "    response:\n"
        "      status: 200\n"
        f"      body: '{body}'\n",
        encoding="utf-8",
    )
    return p


def test_validate_scans_archived_fixtures_for_pii(tmp_path):  # FR-023
    repo = _stage_repo_with_fixtures(
        tmp_path, http_yaml="name: x\nversion: 2\nmatchers: []\n"
    )
    _write_archived(repo / "processes" / "demo-bp", "http-x", 1,
                    "Bearer abcdef1234567890")
    r = CliRunner().invoke(main, ["validate"], obj={"cwd": repo})
    assert r.exit_code == 0, r.output  # warning, not error
    assert "PII suspect" in r.output or "Bearer" in r.output


def test_validate_archived_fixtures_no_new_errors_when_clean(tmp_path):  # SC-002
    repo = _stage_repo_with_fixtures(
        tmp_path, http_yaml="name: x\nversion: 2\nmatchers: []\n"
    )
    _write_archived(repo / "processes" / "demo-bp", "http-x", 1, "clean-body")
    r = CliRunner().invoke(main, ["validate"], obj={"cwd": repo})
    assert r.exit_code == 0, r.output
