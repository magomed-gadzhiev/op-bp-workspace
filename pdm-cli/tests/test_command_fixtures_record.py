import json
from pathlib import Path
from click.testing import CliRunner
import pytest
from pdm_cli.cli import main


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "pdm.config.yaml").write_text("""
endpoints:
  sandbox: http://sandbox.local
  hoverfly: http://hoverfly:8888
egress:
  http:
    redact:
      - regex: 'Bearer [A-Za-z0-9]+'
        replacement: 'Bearer <token>'
""", encoding="utf-8")
    (tmp_path / "processes" / "demo-bp").mkdir(parents=True)
    (tmp_path / "processes" / "demo-bp" / "manifest.yaml").write_text(
        "slug: demo-bp\nname: Demo\nstatus: draft\nversion: 0\n", encoding="utf-8"
    )
    return tmp_path


def test_fixtures_record_writes_yaml_with_redaction(repo, mocker):
    fake_sim = {
        "data": {"pairs": [{
            "request": {
                "method":[{"matcher":"exact","value":"GET"}],
                "destination":[{"matcher":"exact","value":"api.partner.local"}],
                "path":[{"matcher":"exact","value":"/v1/balance"}],
                "scheme":[{"matcher":"exact","value":"https"}],
                "headers":{"Authorization":[{"matcher":"exact","value":"Bearer abc123"}]},
            },
            "response": {"status":200,"body":'{"balance":100}',"headers":{}}
        }]},
        "meta": {"schemaVersion":"v5.2"}
    }
    mocker.patch("pdm_cli.commands.fixtures.HoverflyClient.get_simulation", return_value=fake_sim)
    runner = CliRunner()
    result = runner.invoke(main, ["fixtures", "record",
                                  "--bp", "demo-bp",
                                  "--case", "happy-path",
                                  "--protocol", "http"],
                           obj={"cwd": repo})
    assert result.exit_code == 0, result.output
    out = repo / "processes" / "demo-bp" / "fixtures" / "http-happy-path.yaml"
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "abc123" not in text
    assert "<token>" in text


def test_fixtures_record_dry_run_does_not_write(repo, mocker):
    mocker.patch("pdm_cli.commands.fixtures.HoverflyClient.get_simulation",
                 return_value={"data":{"pairs":[]}, "meta":{"schemaVersion":"v5.2"}})
    runner = CliRunner()
    result = runner.invoke(main, ["fixtures","record","--bp","demo-bp","--case","empty",
                                  "--protocol","http","--dry-run"], obj={"cwd": repo})
    assert result.exit_code == 0
    assert "[dry-run]" in result.output
    assert not (repo / "processes/demo-bp/fixtures/http-empty.yaml").exists()


def test_fixtures_record_from_file(repo, tmp_path):
    sim_path = tmp_path / "sim.json"
    sim_path.write_text(json.dumps({
        "data": {"pairs": [{
            "request":{"method":[{"matcher":"exact","value":"GET"}],
                       "destination":[{"matcher":"exact","value":"x.local"}],
                       "path":[{"matcher":"exact","value":"/"}],
                       "scheme":[{"matcher":"exact","value":"http"}]},
            "response":{"status":200,"body":"ok","headers":{}}
        }]},
        "meta":{"schemaVersion":"v5.2"}
    }), encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(main, ["fixtures","record","--bp","demo-bp","--case","static",
                                  "--protocol","http","--from-file",str(sim_path)],
                           obj={"cwd": repo})
    assert result.exit_code == 0
    assert (repo / "processes/demo-bp/fixtures/http-static.yaml").is_file()


# ---------------------------------------------------------------------------
# E16 US1 — record stamps version + recorded_at (SC-001 / FR-001 / D4)
# ---------------------------------------------------------------------------

_SIM = {
    "data": {"pairs": [{
        "request": {"method": [{"matcher": "exact", "value": "GET"}],
                    "destination": [{"matcher": "exact", "value": "x.local"}],
                    "path": [{"matcher": "exact", "value": "/"}],
                    "scheme": [{"matcher": "exact", "value": "http"}]},
        "response": {"status": 200, "body": "ok", "headers": {}}
    }]},
    "meta": {"schemaVersion": "v5.2"},
}


def test_record_new_case_stamps_v1_and_recorded_at(repo, tmp_path):
    from pdm_cli.fixtures.http import load_http_fixture

    sim_path = tmp_path / "sim.json"
    sim_path.write_text(json.dumps(_SIM), encoding="utf-8")
    r = CliRunner().invoke(main, ["fixtures", "record", "--bp", "demo-bp", "--case", "stamp",
                                  "--protocol", "http", "--from-file", str(sim_path)],
                           obj={"cwd": repo})
    assert r.exit_code == 0, r.output
    fix = load_http_fixture(repo / "processes/demo-bp/fixtures/http-stamp.yaml")
    assert fix.version == 1
    assert fix.recorded_at is not None
    assert fix.recorded_at.endswith("Z")  # UTC ISO-8601


def test_rerecord_preserves_version_refreshes_recorded_at(repo, tmp_path):
    from pdm_cli.fixtures.http import load_http_fixture

    out = repo / "processes/demo-bp/fixtures/http-keep.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "name: keep\nversion: 3\nrecorded_at: 2020-01-01T00:00:00Z\nmatchers: []\n",
        encoding="utf-8",
    )
    sim_path = tmp_path / "sim.json"
    sim_path.write_text(json.dumps(_SIM), encoding="utf-8")
    r = CliRunner().invoke(main, ["fixtures", "record", "--bp", "demo-bp", "--case", "keep",
                                  "--protocol", "http", "--from-file", str(sim_path)],
                           obj={"cwd": repo})
    assert r.exit_code == 0, r.output
    fix = load_http_fixture(out)
    assert fix.version == 3  # preserved on re-record (D4)
    assert fix.recorded_at != "2020-01-01T00:00:00Z"  # refreshed
