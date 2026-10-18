"""Etap 7 Phase 2 — Hoverfly snapshot/PUT-merge/restore mechanism."""
import copy
import json as _j

import respx
import pytest

from pdm_cli.sandbox_mcp.hoverfly_override import (
    HoverflyOverrideContext, _to_hoverfly_pair,
)


BASELINE = {
    "data": {
        "pairs": [
            {"request": {"method": [{"matcher": "exact", "value": "GET"}],
                         "destination": [{"matcher": "exact", "value": "ex.local"}]},
             "response": {"status": 200, "body": "baseline", "encodedBody": False}}
        ],
        "globalActions": {"delays": []},
    },
    "meta": {"schemaVersion": "v5"},
}


def test_snapshot_inject_restore_roundtrip_preserves_baseline():
    base = copy.deepcopy(BASELINE)
    with respx.mock(base_url="http://hf.local") as rx:
        rx.get("/api/v2/simulation").respond(200, json=base)
        put_route = rx.put("/api/v2/simulation").respond(200, json={})
        with HoverflyOverrideContext("http://hf.local") as ctx:
            ctx.inject([{"request": {"method": [{"matcher": "exact", "value": "POST"}]},
                         "response": {"status": 201, "body": "over"}}])
    # Last PUT must equal baseline (restore)
    last_put_body = put_route.calls[-1].request.read().decode()
    assert _j.loads(last_put_body) == base


def test_inject_prepends_override_pairs():
    base = copy.deepcopy(BASELINE)
    with respx.mock(base_url="http://hf.local") as rx:
        rx.get("/api/v2/simulation").respond(200, json=base)
        put_route = rx.put("/api/v2/simulation").respond(200, json={})
        with HoverflyOverrideContext("http://hf.local") as ctx:
            ctx.inject([{"request": {}, "response": {"status": 999}}])
    first_put = _j.loads(put_route.calls[0].request.read().decode())
    pairs = first_put["data"]["pairs"]
    assert pairs[0]["response"]["status"] == 999
    assert pairs[-1]["response"]["body"] == "baseline"


def test_restore_runs_even_on_exception():
    base = copy.deepcopy(BASELINE)
    with respx.mock(base_url="http://hf.local") as rx:
        rx.get("/api/v2/simulation").respond(200, json=base)
        put_route = rx.put("/api/v2/simulation").respond(200, json={})
        with pytest.raises(RuntimeError):
            with HoverflyOverrideContext("http://hf.local") as ctx:
                ctx.inject([{"request": {}, "response": {"status": 500}}])
                raise RuntimeError("boom")
    assert put_route.call_count >= 2


def test_to_hoverfly_pair_converts_simple_matcher():
    pair = _to_hoverfly_pair(
        {"method": "POST", "host": "api.x.local",
         "path": "/v1/things", "body_contains": "rate="},
        {"status": 201, "body": "{}", "headers": {"Content-Type": "application/json"}},
    )
    req = pair["request"]
    assert req["method"][0]["value"] == "POST"
    assert req["destination"][0]["value"] == "api.x.local"
    assert req["path"][0]["matcher"] == "exact"
    assert req["path"][0]["value"] == "/v1/things"
    assert req["body"][0]["matcher"] == "contains"
    resp = pair["response"]
    assert resp["status"] == 201
    assert resp["headers"]["Content-Type"] == ["application/json"]
    assert resp["postServeAction"] == "log-egress"


def test_to_hoverfly_pair_uses_glob_for_wildcard_path():
    pair = _to_hoverfly_pair(
        {"method": "GET", "host": "x.local", "path": "/v1/*/bonus"},
        {"status": 200},
    )
    assert pair["request"]["path"][0]["matcher"] == "glob"
