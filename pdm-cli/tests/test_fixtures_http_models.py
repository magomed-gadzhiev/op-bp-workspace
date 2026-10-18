from pathlib import Path

import pytest
from pydantic import ValidationError

from pdm_cli.fixtures.http import (
    HttpFixture,
    HttpMatcher,
    HttpRequest,
    HttpResponse,
    load_http_fixture,
    dump_http_fixture,
)

SAMPLE = Path(__file__).parent / "fixtures" / "sample-fixtures" / "http-happy-path.yaml"


def test_load_minimal_http_fixture():
    fix = load_http_fixture(SAMPLE)
    assert fix.name == "happy-path"
    assert len(fix.matchers) == 1
    m = fix.matchers[0]
    assert m.request.method == "POST"
    assert m.request.url_matches == r"https://api\.partner\.local/v1/payments"
    assert m.response.status == 200
    assert "transaction_id" in m.response.body


def test_http_fixture_round_trip(tmp_path):
    fix = load_http_fixture(SAMPLE)
    out = tmp_path / "out.yaml"
    dump_http_fixture(fix, out)
    fix2 = load_http_fixture(out)
    assert fix == fix2


# ---------------------------------------------------------------------------
# E16 fixture hygiene — version / recorded_at fields (C-V1, C-V2, C-V3)
# ---------------------------------------------------------------------------


def _sample_matcher() -> HttpMatcher:
    return HttpMatcher(
        request=HttpRequest(method="GET", url_matches=r"https://x\.local/y"),
        response=HttpResponse(status=200, body="ok"),
    )


def test_http_fixture_legacy_loads_as_v1(tmp_path):  # C-V1
    """A YAML without version/recorded_at loads as v1 / None with no error (FR-003/FR-008)."""
    p = tmp_path / "http-legacy.yaml"
    p.write_text(
        "name: legacy\n"
        "matchers:\n"
        "  - request:\n"
        "      method: GET\n"
        "      url_matches: 'https://x\\.local/y'\n"
        "    response:\n"
        "      status: 200\n"
        "      body: ok\n",
        encoding="utf-8",
    )
    fix = load_http_fixture(p)
    assert fix.version == 1
    assert fix.recorded_at is None


def test_http_fixture_round_trips_version_fields(tmp_path):  # C-V2
    """dump writes version/recorded_at after name; load(dump(x)) == x (FR-001)."""
    fix = HttpFixture(
        name="x", version=2, recorded_at="2026-05-20T12:00:00Z",
        matchers=[_sample_matcher()],
    )
    out = tmp_path / "http-x.yaml"
    dump_http_fixture(fix, out)
    text = out.read_text(encoding="utf-8")
    assert (
        text.index("name:")
        < text.index("version:")
        < text.index("recorded_at:")
        < text.index("matchers:")
    )
    assert load_http_fixture(out) == fix


def test_http_fixture_rejects_version_below_one():  # C-V3
    with pytest.raises(ValidationError):
        HttpFixture(name="x", version=0, matchers=[_sample_matcher()])
