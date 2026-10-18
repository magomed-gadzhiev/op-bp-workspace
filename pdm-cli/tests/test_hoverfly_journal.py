"""Tests for pdm_cli.test_runner.hoverfly_journal (HTTP side-effect queries)."""
import httpx
import respx

from pdm_cli.test_case import HttpSideEffect
from pdm_cli.test_runner.hoverfly_journal import (
    clear_journal,
    get_journal,
    match_http_side_effect,
)


@respx.mock
def test_clear_journal_deletes():
    route = respx.delete("http://hoverfly:8888/api/v2/journal").mock(
        return_value=httpx.Response(200, json={})
    )
    clear_journal("http://hoverfly:8888")
    assert route.called


@respx.mock
def test_clear_journal_strips_trailing_slash():
    route = respx.delete("http://hoverfly:8888/api/v2/journal").mock(
        return_value=httpx.Response(200, json={})
    )
    clear_journal("http://hoverfly:8888/")
    assert route.called


@respx.mock
def test_get_journal_returns_entries():
    respx.get("http://hoverfly:8888/api/v2/journal").mock(
        return_value=httpx.Response(200, json={"journal": [{"x": 1}, {"x": 2}]})
    )
    entries = get_journal("http://hoverfly:8888")
    assert entries == [{"x": 1}, {"x": 2}]


@respx.mock
def test_get_journal_handles_missing_key():
    respx.get("http://hoverfly:8888/api/v2/journal").mock(
        return_value=httpx.Response(200, json={})
    )
    assert get_journal("http://hoverfly:8888") == []


@respx.mock
def test_match_http_side_effect_filters_by_method_and_url():
    respx.get("http://hoverfly:8888/api/v2/journal").mock(
        return_value=httpx.Response(200, json={"journal": [
            {"request": {"method": "POST", "destination": "api.x.com",
                         "path": "/api/v3/work_packages", "body": '{"name":"x"}'},
             "response": {"status": 201}},
            {"request": {"method": "GET", "destination": "api.x.com",
                         "path": "/healthz", "body": ""},
             "response": {"status": 200}},
        ]})
    )
    eff = HttpSideEffect(
        kind="http", method="POST", url_matches="work_packages", min_count=1
    )
    matches = match_http_side_effect("http://hoverfly:8888", eff)
    assert len(matches) == 1
    assert matches[0]["request"]["path"] == "/api/v3/work_packages"


@respx.mock
def test_match_http_body_contains_AND():
    respx.get("http://hoverfly:8888/api/v2/journal").mock(
        return_value=httpx.Response(200, json={"journal": [
            {"request": {"method": "POST", "destination": "x", "path": "/a",
                         "body": "satisfaction=4.5"},
             "response": {"status": 200}},
            {"request": {"method": "POST", "destination": "x", "path": "/a",
                         "body": "only satisfaction"},
             "response": {"status": 200}},
        ]})
    )
    eff = HttpSideEffect(
        kind="http", url_matches="/a",
        body_contains=["satisfaction", "4.5"],
    )
    matches = match_http_side_effect("http://hoverfly:8888", eff)
    assert len(matches) == 1
    assert matches[0]["request"]["body"] == "satisfaction=4.5"


@respx.mock
def test_match_http_no_method_matches_any():
    respx.get("http://hoverfly:8888/api/v2/journal").mock(
        return_value=httpx.Response(200, json={"journal": [
            {"request": {"method": "POST", "destination": "x", "path": "/a", "body": ""},
             "response": {"status": 200}},
            {"request": {"method": "GET", "destination": "x", "path": "/a", "body": ""},
             "response": {"status": 200}},
        ]})
    )
    eff = HttpSideEffect(kind="http", url_matches="/a")
    matches = match_http_side_effect("http://hoverfly:8888", eff)
    assert len(matches) == 2


@respx.mock
def test_match_http_url_regex_no_match():
    respx.get("http://hoverfly:8888/api/v2/journal").mock(
        return_value=httpx.Response(200, json={"journal": [
            {"request": {"method": "POST", "destination": "api.x.com", "path": "/foo",
                         "body": ""},
             "response": {"status": 200}},
        ]})
    )
    eff = HttpSideEffect(kind="http", url_matches=r"^https://other\.com")
    matches = match_http_side_effect("http://hoverfly:8888", eff)
    assert matches == []


@respx.mock
def test_match_http_url_regex_combines_destination_and_path():
    respx.get("http://hoverfly:8888/api/v2/journal").mock(
        return_value=httpx.Response(200, json={"journal": [
            {"request": {"method": "POST", "destination": "api.partner.local",
                         "path": "/v1/payments", "body": ""},
             "response": {"status": 200}},
        ]})
    )
    eff = HttpSideEffect(kind="http", url_matches=r"api\.partner\.local/v1/payments")
    matches = match_http_side_effect("http://hoverfly:8888", eff)
    assert len(matches) == 1


@respx.mock
def test_match_http_handles_null_body_fields():
    respx.get("http://hoverfly:8888/api/v2/journal").mock(
        return_value=httpx.Response(200, json={"journal": [
            {"request": {"method": "POST", "destination": None, "path": "/a",
                         "body": None},
             "response": {"status": 200}},
        ]})
    )
    eff = HttpSideEffect(kind="http", url_matches="/a", body_contains=["x"])
    assert match_http_side_effect("http://hoverfly:8888", eff) == []
    eff2 = HttpSideEffect(kind="http", url_matches="/a")
    assert len(match_http_side_effect("http://hoverfly:8888", eff2)) == 1
