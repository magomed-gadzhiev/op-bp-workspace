"""Etap 7 — api_client extensions for replay_step + run_details(include_script_output)
+ entity_clone_with_overrides."""
import respx
import pytest

from pdm_cli.api_client import PdmApiClient, SandboxLockConflict


def test_replay_step_calls_endpoint():
    api = PdmApiClient(base_url="http://t.local", api_key="k")
    with respx.mock(base_url="http://t.local") as rx:
        rx.post("/api/process-instances/42/replay_step/").respond(
            200, json={"executed": True, "result": {"ok": 1}})
        out = api.replay_step("42", "calc", {"x": 1})
    assert out["executed"] is True


def test_replay_step_sends_override_owner_header():
    api = PdmApiClient(base_url="http://t.local", api_key="k")
    with respx.mock(base_url="http://t.local") as rx:
        route = rx.post("/api/process-instances/42/replay_step/").respond(
            200, json={"executed": True})
        api.replay_step("42", "calc", {"x": 1}, override_owner="owner-1")
    assert route.calls[0].request.headers["X-PDM-Override-Owner"] == "owner-1"


def test_replay_step_409_raises_lock_conflict():
    api = PdmApiClient(base_url="http://t.local", api_key="k")
    with respx.mock(base_url="http://t.local") as rx:
        rx.post("/api/process-instances/42/replay_step/").respond(
            409, json={"current_owner": "other", "retry_after": 10})
        with pytest.raises(SandboxLockConflict) as exc:
            api.replay_step("42", "calc", {}, override_owner="owner-1")
    assert exc.value.body["current_owner"] == "other"


def test_run_details_passes_include_script_output_flag():
    api = PdmApiClient(base_url="http://t.local", api_key="k")
    with respx.mock(base_url="http://t.local") as rx:
        route = rx.get("/api/process-instances/42/details/").respond(
            200, json={"status": "ok"})
        api.run_details("42", include_script_output=True)
    assert any("include_script_output=1" in str(c.request.url)
               for c in route.calls)


def test_entity_clone_with_overrides_merges_then_posts():
    api = PdmApiClient(base_url="http://t.local", api_key="k")
    with respx.mock(base_url="http://t.local") as rx:
        rx.get("/api/entities/100/").respond(200, json={
            "id": 100, "entity_type": 7,
            "data": {"name": "orig", "salary": 30000}})
        rx.post("/api/entities/").respond(201, json={
            "id": 101, "entity_type": 7,
            "data": {"name": "orig", "salary": 50000}})
        new = api.entity_clone_with_overrides(100, {"salary": 50000})
    assert new["id"] == 101
    assert new["data"]["salary"] == 50000
