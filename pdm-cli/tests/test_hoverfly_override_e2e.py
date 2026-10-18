"""Etap 7 Phase 2 — live Hoverfly snapshot/inject/restore E2E."""
import os
import httpx
import pytest

from pdm_cli.sandbox_mcp.hoverfly_override import (
    HoverflyOverrideContext, _to_hoverfly_pair,
)

pytestmark = pytest.mark.e2e
HOVERFLY = os.environ.get("HOVERFLY_ADMIN", "http://localhost:8888")
ENABLED = os.environ.get("PDM_E2E") == "1"


@pytest.mark.skipif(not ENABLED, reason="set PDM_E2E=1")
def test_live_hoverfly_override_restore():
    try:
        httpx.get(f"{HOVERFLY}/api/health", timeout=3)
    except Exception:
        pytest.skip("Hoverfly admin not reachable")

    override = _to_hoverfly_pair(
        {"method": "GET", "host": "ephemeral.local", "path": "/probe"},
        {"status": 418, "body": "I am a teapot"},
    )
    with HoverflyOverrideContext(HOVERFLY) as ctx:
        ctx.inject([override])
        sim = httpx.get(f"{HOVERFLY}/api/v2/simulation", timeout=5).json()
        assert any(
            "ephemeral.local" in str(p.get("request", {}).get("destination", ""))
            for p in sim["data"]["pairs"]
        )
    sim2 = httpx.get(f"{HOVERFLY}/api/v2/simulation", timeout=5).json()
    assert not any(
        "ephemeral.local" in str(p.get("request", {}).get("destination", ""))
        for p in sim2["data"]["pairs"]
    )
