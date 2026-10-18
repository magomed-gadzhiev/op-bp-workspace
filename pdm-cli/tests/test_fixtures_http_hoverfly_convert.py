"""Tests for Hoverfly simulation ↔ HttpFixture converters."""
from pdm_cli.fixtures.http import from_hoverfly_pair

PAIR = {
    "request": {
        "method": [{"matcher": "exact", "value": "POST"}],
        "destination": [{"matcher": "exact", "value": "api.partner.local"}],
        "path": [{"matcher": "exact", "value": "/v1/payments"}],
        "scheme": [{"matcher": "exact", "value": "https"}],
        "headers": {"Content-Type": [{"matcher": "exact", "value": "application/json"}]},
    },
    "response": {"status": 200, "body": '{"ok":true}', "headers": {"Content-Type": ["application/json"]}},
}


def test_from_hoverfly_pair_builds_matcher():
    m = from_hoverfly_pair(PAIR)
    assert m.request.method == "POST"
    assert m.request.url_matches == r"https://api\.partner\.local/v1/payments"
    assert m.request.headers["Content-Type"] == "application/json"
    assert m.response.status == 200
    assert m.response.headers["Content-Type"] == "application/json"


def test_round_trip_to_hoverfly():
    from pdm_cli.fixtures.http import HttpMatcher, HttpRequest, HttpResponse, to_hoverfly_pair, from_hoverfly_pair
    m = HttpMatcher(
        request=HttpRequest(
            method="POST",
            url_matches=r"https://api\.partner\.local/v1/payments",
            headers={"X-Trace": "abc"},
            body_contains=['"amount":'],
        ),
        response=HttpResponse(status=201, body='{"id":42}', headers={"Content-Type": "application/json"}, delay_ms=50),
    )
    pair = to_hoverfly_pair(m)
    assert pair["response"]["postServeAction"] == "log-egress"
    m2 = from_hoverfly_pair(pair)
    assert m2.request.method == "POST"
    assert m2.request.headers == {"X-Trace": "abc"}
    assert m2.request.body_contains == ['"amount":']
    assert m2.response.status == 201
    assert m2.response.headers["Content-Type"] == "application/json"
    assert m2.response.delay_ms == 50


def test_simulation_round_trip():
    from pdm_cli.fixtures.http import HttpFixture, HttpMatcher, HttpRequest, HttpResponse
    from pdm_cli.fixtures.http import fixture_to_hoverfly_simulation, hoverfly_simulation_to_fixtures
    fix = HttpFixture(
        name="c1",
        matchers=[
            HttpMatcher(
                request=HttpRequest(method="GET", url_matches=r"https://a\.local/x"),
                response=HttpResponse(status=200, body="ok"),
            )
        ],
    )
    sim = fixture_to_hoverfly_simulation([fix])
    assert sim["meta"]["schemaVersion"] == "v5.2"
    assert sim["data"]["pairs"][0]["response"]["postServeAction"] == "log-egress"
    back = hoverfly_simulation_to_fixtures(sim, case_name="c1")
    assert len(back.matchers) == 1
    assert back.matchers[0].response.body == "ok"
