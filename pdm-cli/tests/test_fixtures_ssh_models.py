from pathlib import Path

import pytest
from pydantic import ValidationError

from pdm_cli.fixtures.ssh import (
    SshFixture,
    SshMatcher,
    SshRequest,
    SshResponse,
    load_ssh_fixture,
    dump_ssh_fixture,
    match_ssh_request,
)

SAMPLE = Path(__file__).parent / "fixtures" / "sample-fixtures" / "ssh-deploy.yaml"


def test_load_ssh_fixture():
    fix = load_ssh_fixture(SAMPLE)
    assert fix.name == "deploy"
    assert len(fix.matchers) == 1
    m = fix.matchers[0]
    assert m.request.host == "deploy.local"
    assert m.request.user == "deployer"
    assert "deploy_release" in m.request.command_matches
    assert m.response.exit_code == 0


def test_round_trip_ssh_fixture(tmp_path):
    fix = load_ssh_fixture(SAMPLE)
    out = tmp_path / "x.yaml"
    dump_ssh_fixture(fix, out)
    assert load_ssh_fixture(out) == fix


def test_match_ssh_request_substitutes_named_groups():
    fix = load_ssh_fixture(SAMPLE)
    resp = match_ssh_request(fix, host="deploy.local", user="deployer",
                             command="deploy_release.sh --version 2.0.1")
    assert resp is not None
    assert resp.stdout == "Deployed version 2.0.1 successfully\n"
    assert resp.exit_code == 0


def test_match_ssh_request_no_match():
    fix = load_ssh_fixture(SAMPLE)
    assert match_ssh_request(fix, host="other.local", user="x", command="ls") is None


def test_from_capture_jsonl_dir_aggregates_multiple_files(tmp_path):
    from pdm_cli.fixtures.ssh import from_capture_jsonl_dir

    bp_dir = tmp_path / "payroll"
    bp_dir.mkdir()
    (bp_dir / "ssh-capture.jsonl").write_text(
        '{"bp":"payroll","host":"deploy.local","user":"deployer",'
        '"command":"deploy.sh --version 1.0","stdout":"ok\\n","stderr":"",'
        '"exit_code":0,"duration_ms":12}\n',
        encoding="utf-8",
    )
    (bp_dir / "ssh-capture-2.jsonl").write_text(
        '{"bp":"payroll","host":"deploy.local","user":"deployer",'
        '"command":"deploy.sh --version 2.0","stdout":"ok2\\n","stderr":"",'
        '"exit_code":0,"duration_ms":15}\n',
        encoding="utf-8",
    )

    fix = from_capture_jsonl_dir(tmp_path, bp_slug="payroll", case_name="happy")
    assert fix.name == "happy"
    assert len(fix.matchers) == 2


def test_from_capture_jsonl_dir_missing_dir_raises(tmp_path):
    from pdm_cli.fixtures.ssh import from_capture_jsonl_dir
    import pytest
    with pytest.raises(FileNotFoundError):
        from_capture_jsonl_dir(tmp_path, bp_slug="ghost", case_name="x")


def test_from_capture_jsonl_dir_empty_dir_raises(tmp_path):
    from pdm_cli.fixtures.ssh import from_capture_jsonl_dir
    import pytest
    (tmp_path / "payroll").mkdir()
    with pytest.raises(FileNotFoundError):
        from_capture_jsonl_dir(tmp_path, bp_slug="payroll", case_name="x")


# ---------------------------------------------------------------------------
# E16 fixture hygiene — version / recorded_at fields, uniform with HTTP (FR-002)
# ---------------------------------------------------------------------------


def _sample_ssh_matcher() -> SshMatcher:
    return SshMatcher(
        request=SshRequest(host="h", user="u", command_matches="ls"),
        response=SshResponse(stdout="ok\n"),
    )


def test_ssh_fixture_legacy_loads_as_v1(tmp_path):  # C-V1 (ssh)
    p = tmp_path / "ssh-legacy.yaml"
    p.write_text(
        "name: legacy\n"
        "matchers:\n"
        "  - request:\n"
        "      host: h\n"
        "      user: u\n"
        "      command_matches: ls\n"
        "    response:\n"
        "      stdout: \"ok\\n\"\n"
        "      exit_code: 0\n",
        encoding="utf-8",
    )
    fix = load_ssh_fixture(p)
    assert fix.version == 1
    assert fix.recorded_at is None


def test_ssh_fixture_round_trips_version_fields(tmp_path):  # C-V2 (ssh)
    fix = SshFixture(
        name="x", version=2, recorded_at="2026-05-20T12:00:00Z",
        matchers=[_sample_ssh_matcher()],
    )
    out = tmp_path / "ssh-x.yaml"
    dump_ssh_fixture(fix, out)
    text = out.read_text(encoding="utf-8")
    assert (
        text.index("name:")
        < text.index("version:")
        < text.index("recorded_at:")
        < text.index("matchers:")
    )
    assert load_ssh_fixture(out) == fix


def test_ssh_fixture_rejects_version_below_one():  # C-V3 (ssh)
    with pytest.raises(ValidationError):
        SshFixture(name="x", version=0, matchers=[_sample_ssh_matcher()])
