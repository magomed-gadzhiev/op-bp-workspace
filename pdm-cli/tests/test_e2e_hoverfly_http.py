"""End-to-end smoke test: capture → record → replay → simulate against real Hoverfly.

Skipped unless PDM_E2E_HOVERFLY=1 is set. Requires sandbox stack up:
  docker compose -f docker-compose.full.yml -f tools/pdm-cli/sandbox/docker-compose.sandbox.yml up -d hoverfly
"""
import os
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from pdm_cli.cli import main
from pdm_cli.fixtures.hoverfly import HoverflyClient

pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def _require_env():
    if not os.environ.get("PDM_E2E_HOVERFLY"):
        pytest.skip("Set PDM_E2E_HOVERFLY=1 to run")


HOVERFLY_URL = os.environ.get("HOVERFLY_URL", "http://hoverfly:8888")
HOVERFLY_PROXY = os.environ.get("HOVERFLY_PROXY", "http://hoverfly:8500")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "pdm.config.yaml").write_text(f"""
endpoints:
  sandbox: http://sandbox.local
  hoverfly: {HOVERFLY_URL}
egress:
  http:
    redact: []
""", encoding="utf-8")
    (tmp_path / "processes" / "demo-bp").mkdir(parents=True)
    (tmp_path / "processes" / "demo-bp" / "manifest.yaml").write_text(
        "slug: demo-bp\nname: Demo\n", encoding="utf-8"
    )
    return tmp_path


def test_capture_record_replay_cycle(repo):
    client = HoverflyClient(HOVERFLY_URL)
    client.delete_simulation()
    client.set_mode("capture")

    with httpx.Client(proxy=HOVERFLY_PROXY, verify=False) as h:
        r = h.get("http://httpbin.org/uuid")
        assert r.status_code == 200
        uuid_captured = r.json()["uuid"]

    runner = CliRunner()
    res = runner.invoke(main, ["fixtures","record","--bp","demo-bp","--case","httpbin","--protocol","http"],
                        obj={"cwd": repo})
    assert res.exit_code == 0, res.output
    yaml_path = repo / "processes/demo-bp/fixtures/http-httpbin.yaml"
    assert yaml_path.is_file()
    assert uuid_captured in yaml_path.read_text(encoding="utf-8")

    client.delete_simulation()
    res = runner.invoke(main, ["fixtures","replay","--bp","demo-bp","--protocol","http"], obj={"cwd": repo})
    assert res.exit_code == 0

    with httpx.Client(proxy=HOVERFLY_PROXY, verify=False) as h:
        r = h.get("http://httpbin.org/uuid")
        assert r.status_code == 200
        assert r.json()["uuid"] == uuid_captured  # served from fixture


def test_capture_record_replay_https(repo):
    client = HoverflyClient(HOVERFLY_URL)
    client.delete_simulation()
    client.set_mode("capture")

    ca = os.environ.get("PDM_E2E_CA_BUNDLE")
    with httpx.Client(proxy=HOVERFLY_PROXY, verify=ca or False) as h:
        r = h.get("https://httpbin.org/uuid")
        assert r.status_code == 200
        captured = r.json()["uuid"]

    runner = CliRunner()
    runner.invoke(main, ["fixtures","record","--bp","demo-bp","--case","https-httpbin","--protocol","http"],
                  obj={"cwd": repo})
    yaml_path = repo / "processes/demo-bp/fixtures/http-https-httpbin.yaml"
    assert captured in yaml_path.read_text(encoding="utf-8")
