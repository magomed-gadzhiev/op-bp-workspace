"""Etap 7 Phase 4 — sandbox.inspect_state + sandbox.list_egress."""
import respx

from pdm_cli.api_client import PdmApiClient
from pdm_cli.sandbox_mcp.tools.inspect import _impl_inspect_state, _impl_list_egress


def _api():
    return PdmApiClient(base_url="http://t.local", api_key="k")


def test_inspect_state_returns_serialized_details():
    with respx.mock(base_url="http://t.local") as rx:
        rx.get("/api/process-instances/77/details/").respond(
            200, json={
                "id": 77, "status": "completed",
                "context_data": {"x": 1},
                "source_run_id": None, "override_payload": None,
                "assignments": [{"step_id": "a", "status": "completed"}],
            })
        out = _impl_inspect_state(_api(), "77")
    assert out["run_id"] == "77"
    assert out["status"] == "completed"
    assert out["context_data"] == {"x": 1}
    assert out["assignments"][0]["step_id"] == "a"


def test_list_egress_extracts_egress_field():
    with respx.mock(base_url="http://t.local") as rx:
        rx.get("/api/process-instances/88/details/").respond(
            200, json={
                "id": 88,
                "egress": {
                    "http": [{"method": "GET", "url": "https://x", "status": 200}],
                    "ssh": [],
                    "orphan_count": {"http": 0, "ssh": 0},
                },
            })
        out = _impl_list_egress(_api(), "88")
    assert out["http"][0]["method"] == "GET"
    assert out["orphan_count"]["http"] == 0
