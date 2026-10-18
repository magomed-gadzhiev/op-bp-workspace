"""Tests for HoverflyClient (Hoverfly Admin API wrapper)."""
import httpx
import respx
import pytest
from pdm_cli.fixtures.hoverfly import HoverflyClient


@respx.mock
def test_get_simulation_returns_pairs():
    route = respx.get("http://hoverfly:8888/api/v2/simulation").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "pairs": [
                    {
                        "request": {"method": [{"matcher": "exact", "value": "POST"}],
                                    "destination": [{"matcher": "exact", "value": "api.partner.local"}],
                                    "path": [{"matcher": "exact", "value": "/v1/payments"}],
                                    "scheme": [{"matcher": "exact", "value": "https"}]},
                        "response": {"status": 200, "body": '{"ok":true}', "headers": {}}
                    }
                ]
            },
            "meta": {"schemaVersion": "v5.2"}
        })
    )
    client = HoverflyClient("http://hoverfly:8888")
    sim = client.get_simulation()
    assert len(sim["data"]["pairs"]) == 1
    assert sim["data"]["pairs"][0]["response"]["status"] == 200
    assert route.called


@respx.mock
def test_put_simulation():
    route = respx.put("http://hoverfly:8888/api/v2/simulation").mock(
        return_value=httpx.Response(200, json={})
    )
    HoverflyClient("http://hoverfly:8888").put_simulation({"data": {"pairs": []}, "meta": {"schemaVersion": "v5.2"}})
    assert route.called
    assert route.calls[0].request.read() != b""


@respx.mock
def test_set_mode_capture():
    route = respx.put("http://hoverfly:8888/api/v2/hoverfly/mode").mock(
        return_value=httpx.Response(200, json={"mode": "capture"})
    )
    HoverflyClient("http://hoverfly:8888").set_mode("capture")
    assert route.called


@respx.mock
def test_delete_simulation():
    route = respx.delete("http://hoverfly:8888/api/v2/simulation").mock(
        return_value=httpx.Response(200, json={})
    )
    HoverflyClient("http://hoverfly:8888").delete_simulation()
    assert route.called
