from pdm_cli.config import RedactRule
from pdm_cli.fixtures.http import HttpFixture, HttpMatcher, HttpRequest, HttpResponse
from pdm_cli.fixtures.redaction import redact_http_fixture


def test_redact_header_value():
    fix = HttpFixture(name="t", matchers=[
        HttpMatcher(
            request=HttpRequest(method="GET", url_matches=".*", headers={"Authorization": "Bearer abc.def.ghi"}),
            response=HttpResponse(status=200, headers={}, body=""),
        )
    ])
    rules = [RedactRule(header="Authorization", replacement="<redacted>")]
    out = redact_http_fixture(fix, rules)
    assert out.matchers[0].request.headers["Authorization"] == "<redacted>"


def test_redact_regex_in_response_body():
    fix = HttpFixture(name="t", matchers=[
        HttpMatcher(
            request=HttpRequest(method="GET", url_matches=".*"),
            response=HttpResponse(status=200, headers={}, body='{"token":"Bearer xyz123"}'),
        )
    ])
    rules = [RedactRule(regex=r"Bearer [A-Za-z0-9]+", replacement="Bearer <token>")]
    out = redact_http_fixture(fix, rules)
    assert "<token>" in out.matchers[0].response.body
    assert "xyz123" not in out.matchers[0].response.body


def test_redact_jsonpath_in_response_body():
    fix = HttpFixture(name="t", matchers=[
        HttpMatcher(
            request=HttpRequest(method="GET", url_matches=".*"),
            response=HttpResponse(status=200, headers={}, body='{"email":"ivan@example.com","name":"Ivan"}'),
        )
    ])
    rules = [RedactRule(jsonpath="$.email", replacement="<email>")]
    out = redact_http_fixture(fix, rules)
    body = out.matchers[0].response.body
    assert "<email>" in body
    assert "ivan@example.com" not in body
